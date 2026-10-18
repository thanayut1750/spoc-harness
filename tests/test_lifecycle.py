"""Lifecycle tests use temporary ports/data and never the interactive services or DB."""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pydantic import SecretStr

from org_harness.config import Settings
from org_harness.lifecycle import LifecycleError, ServiceManager


def unused_port():
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return handle.getsockname()[1]


@pytest.fixture
def manager(tmp_path):
    settings = Settings(
        _env_file=None,
        storage_backend="postgres",
        harness_test_mode=True,
        data_dir=tmp_path / "harness",
        api_port=unused_port(),
        api_host="127.0.0.1",
        database_url="postgresql://unused-isolated-test",
    )
    value = ServiceManager(settings)
    yield value
    # Only identities created in this test's private state directory are considered.
    value.stop(timeout=5, force=True)


@pytest.fixture
async def running_manager(tmp_path, postgres_url):
    from org_harness.worker import migrate

    settings = Settings(
        _env_file=None,
        storage_backend="postgres",
        harness_test_mode=True,
        data_dir=tmp_path / "harness",
        api_host="127.0.0.1",
        api_port=unused_port(),
        database_url=postgres_url,
    )
    await migrate(settings)
    value = ServiceManager(settings)
    yield value
    value.stop(timeout=5, force=True)


def test_real_services_start_idempotently_restart_and_stop_with_resolved_settings(running_manager):
    manager = running_manager
    first = manager.start(timeout=10)
    assert first["services"]["api"]["ready"]
    assert first["services"]["worker"]["readiness"] == "process_started"
    response = httpx.get(f"{manager.api_url}/readyz", trust_env=False).json()
    assert response == {"status": "ready", "mode": "demo", "storage": "postgres"}
    second = ServiceManager(manager.settings).start(timeout=10)
    assert {role: value["pid"] for role, value in first["services"].items()} == {
        role: value["pid"] for role, value in second["services"].items()
    }
    state = json.loads(manager.state_path.read_text())
    assert "unused-isolated-test" not in manager.state_path.read_text()
    for role, record in state["services"].items():
        assert record["service"] == role
        assert record["cwd"] == str(manager.cwd)
        assert record["uid"] == os.getuid()
        assert record["start_time"]
        assert record["boot_id"]
        assert record["argv"][:3] == [sys.executable, "-m", "org_harness.cli"]
        assert manager.logs[role].parent == manager.settings.data_dir
    restarted = manager.restart(timeout=10)
    for role in ("api", "worker"):
        assert restarted["services"][role]["pid"] != first["services"][role]["pid"]
    stopped = manager.stop(timeout=10)
    assert all(value["status"] == "stopped" for value in stopped["services"].values())
    assert manager.stop(timeout=1) == stopped
    assert manager.settings.data_dir.exists()
    assert (manager.directory / "manager.lock").exists()


def test_parallel_starts_use_one_process_pair(running_manager):
    manager = running_manager
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: ServiceManager(manager.settings).start(timeout=10), range(2))
        )
    assert results[0]["services"]["api"]["pid"] == results[1]["services"]["api"]["pid"]
    assert results[0]["services"]["worker"]["pid"] == results[1]["services"]["worker"]["pid"]


def test_port_collision_does_not_signal_unrelated_listener(manager):
    with socket.socket() as listener:
        listener.bind((manager.settings.api_host, manager.settings.api_port))
        listener.listen()
        with pytest.raises(LifecycleError, match="occupied or unavailable"):
            manager.start(timeout=1)
        assert listener.fileno() >= 0
        assert json.loads(manager.state_path.read_text())["services"] == {}


def test_foreign_legacy_pid_is_never_signalled(manager, monkeypatch):
    manager.data_dir.mkdir(parents=True)
    (manager.data_dir / "worker.pid").write_text(str(os.getpid()))
    signals = []
    monkeypatch.setattr(signal, "pidfd_send_signal", lambda *args: signals.append(args))
    try:
        with pytest.raises(LifecycleError, match="unrelated"):
            manager.stop(timeout=1)
        assert not signals
    finally:
        (manager.data_dir / "worker.pid").unlink()


def test_changed_start_time_or_argv_prevents_signal(running_manager, monkeypatch):
    manager = running_manager
    manager.start(timeout=10)
    original = manager.state_path.read_text()
    state = json.loads(original)
    state["services"]["worker"]["start_time"] = "0"
    manager.state_path.write_text(json.dumps(state))
    signals = []
    with monkeypatch.context() as context:
        context.setattr(signal, "pidfd_send_signal", lambda *args: signals.append(args))
        with pytest.raises(LifecycleError, match="identity changed"):
            manager.stop(timeout=1, force=True)
        assert not signals
    manager.state_path.write_text(original)


def test_verified_legacy_processes_are_adopted_and_plain_pid_files_removed(running_manager):
    manager = running_manager
    manager.data_dir.mkdir(parents=True)
    environment = {**os.environ, **manager.environment}
    children = {}
    try:
        for role, command in (("api", "serve"), ("worker", "worker")):
            child = subprocess.Popen(
                [sys.executable, str(manager.cwd / ".venv/bin/spoc"), command],
                cwd=manager.cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            children[role] = child
            (manager.data_dir / f"{role}.pid").write_text(str(child.pid))
        result = manager.start(timeout=10)
        for role, child in children.items():
            assert result["services"][role]["pid"] == child.pid
            assert not (manager.data_dir / f"{role}.pid").exists()
        manager.stop(timeout=10)
        for child in children.values():
            child.wait(timeout=5)
    finally:
        for child in children.values():
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                child.wait(timeout=5)


def test_partial_startup_rollback_preserves_preexisting_worker(running_manager, monkeypatch):
    manager = running_manager
    original_spawn = manager._spawn
    worker = original_spawn("worker")
    manager._write({"worker": worker})
    created = []

    def spawn(role):
        record = original_spawn(role)
        created.append(record)
        return record

    monkeypatch.setattr(manager, "_spawn", spawn)
    monkeypatch.setattr(httpx.Client, "get", lambda *args, **kwargs: httpx.Response(503))
    with pytest.raises(LifecycleError, match="did not become ready"):
        manager.start(timeout=1)
    assert manager._inspect(worker["pid"]) is not None
    assert len(created) == 1
    assert manager._inspect(created[0]["pid"]) is None
    assert set(json.loads(manager.state_path.read_text())["services"]) == {"worker"}


def test_restart_keeps_lock_across_stop_and_start(manager, monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def stop_records(*args):
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(manager, "_stop_records", stop_records)
    monkeypatch.setattr(manager, "_start", lambda *args: {"test": "started"})
    with ThreadPoolExecutor(max_workers=1) as pool:
        operation = pool.submit(manager.restart, 1)
        assert entered.wait(5)
        try:
            with pytest.raises(LifecycleError, match="Another lifecycle command"):
                ServiceManager(manager.settings).start(timeout=0.1)
        finally:
            release.set()
        assert operation.result() == {"test": "started"}


def test_timeout_does_not_force_signal_without_explicit_flag(running_manager, monkeypatch):
    manager = running_manager
    manager.start(timeout=10)
    sent = []
    original_signal = manager._signal

    def observe(record, role, signum):
        sent.append((role, signum))

    monkeypatch.setattr(manager, "_signal", observe)
    monkeypatch.setattr(manager, "_wait_gone", lambda *args: False)
    with pytest.raises(LifecycleError, match="still shutting down"):
        manager.stop(timeout=0.1)
    assert sent == [("worker", signal.SIGINT)]
    monkeypatch.setattr(manager, "_signal", original_signal)


def test_stale_record_is_removed_without_signal(manager, monkeypatch):
    manager._write({"worker": {"pid": 2_000_000_000, "service": "worker"}})
    signals = []
    monkeypatch.setattr(signal, "pidfd_send_signal", lambda *args: signals.append(args))
    assert manager.stop(timeout=1)["services"]["worker"]["status"] == "stopped"
    assert not signals


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_is_actionable(manager, timeout):
    with pytest.raises(LifecycleError, match="positive"):
        manager.start(timeout=timeout)


def test_managed_services_refuse_unshared_memory_storage(manager):
    settings = manager.settings.model_copy(update={"storage_backend": "memory"})
    with pytest.raises(LifecycleError, match="shared Postgres"):
        ServiceManager(settings).start(timeout=1)


def test_repeated_stop_sends_sigint_once_and_start_refuses_stopping_service(
    running_manager, monkeypatch
):
    manager = running_manager
    manager.start(timeout=10)
    sent = []
    with monkeypatch.context() as context:
        context.setattr(
            manager, "_signal", lambda record, role, signum: sent.append((role, signum))
        )
        context.setattr(manager, "_wait_gone", lambda *args: False)
        for _ in range(2):
            with pytest.raises(LifecycleError, match="still shutting down"):
                manager.stop(timeout=0.1)
        assert sent == [("worker", signal.SIGINT)]
        with pytest.raises(LifecycleError, match="still stopping"):
            manager.start(timeout=1)
    # The signal was mocked, so restore the fixture to its actual un-signalled state.
    state = json.loads(manager.state_path.read_text())
    state["services"]["worker"].pop("stopping")
    manager.state_path.write_text(json.dumps(state))


def test_unknown_legacy_configuration_requires_restart_but_can_stop(running_manager):
    manager = running_manager
    manager.data_dir.mkdir(parents=True)
    environment = {**os.environ, **manager.environment}
    environment.pop("SPOC_SERVICE_MANAGER_CONFIG")
    child = subprocess.Popen(
        [sys.executable, "-m", "org_harness.cli", "worker"],
        cwd=manager.cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        (manager.data_dir / "worker.pid").write_text(str(child.pid))
        with pytest.raises(LifecycleError, match="configuration is unknown"):
            manager.start(timeout=1)
        record = json.loads(manager.state_path.read_text())["services"]["worker"]
        assert record["config_identity"] is None
        manager.stop(timeout=5)
        child.wait(timeout=5)
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGINT)
            child.wait(timeout=5)


@pytest.mark.parametrize("action", ["stop", "restart"])
def test_verified_legacy_configuration_drift_can_stop_or_restart(running_manager, action):
    manager = running_manager
    old_settings = manager.settings.model_copy(update={"main_model": "previous-model"})
    old_manager = ServiceManager(old_settings)
    manager.data_dir.mkdir(parents=True)
    child = subprocess.Popen(
        [sys.executable, "-m", "org_harness.cli", "worker"],
        cwd=manager.cwd,
        env={**os.environ, **old_manager.environment},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        (manager.data_dir / "worker.pid").write_text(str(child.pid))
        with pytest.raises(LifecycleError, match="settings changed"):
            manager.start(timeout=1)
        record = json.loads(manager.state_path.read_text())["services"]["worker"]
        assert record["config_identity"] == old_manager.config_identity
        result = getattr(manager, action)(timeout=10)
        child.wait(timeout=5)
        if action == "restart":
            assert result["services"]["worker"]["pid"] != child.pid
            current = httpx.get(f"{manager.api_url}/api/settings", trust_env=False).json()
            assert current["model_config"]["model"] == manager.settings.main_model
        else:
            assert result["services"]["worker"]["status"] == "stopped"
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)


def test_legacy_process_in_different_data_directory_is_not_signalled(running_manager):
    manager = running_manager
    foreign_settings = manager.settings.model_copy(
        update={"data_dir": manager.data_dir.parent / "other-harness"}
    )
    foreign = ServiceManager(foreign_settings)
    manager.data_dir.mkdir(parents=True)
    child = subprocess.Popen(
        [sys.executable, "-m", "org_harness.cli", "worker"],
        cwd=manager.cwd,
        env={**os.environ, **foreign.environment},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        (manager.data_dir / "worker.pid").write_text(str(child.pid))
        for action in ("stop", "restart"):
            with pytest.raises(LifecycleError, match="different data directory"):
                getattr(manager, action)(timeout=1)
            assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=5)
        (manager.data_dir / "worker.pid").unlink(missing_ok=True)


def test_spawned_child_is_rolled_back_when_state_write_fails(manager, monkeypatch):
    original_write = manager._write
    writes = 0

    def fail_after_loading(state):
        nonlocal writes
        writes += 1
        if writes > 1:
            raise OSError("Simulated disk failure")
        original_write(state)

    with monkeypatch.context() as context:
        context.setattr(manager, "_write", fail_after_loading)
        with pytest.raises(LifecycleError, match="state/log permissions"):
            manager.start(timeout=1)
    assert manager._children
    assert all(child.poll() is not None for child in manager._children.values())


def test_spawned_child_is_rolled_back_when_identity_capture_fails(manager, monkeypatch):
    with monkeypatch.context() as context:
        context.setattr(
            manager,
            "_inspect",
            lambda pid: (_ for _ in ()).throw(LifecycleError("Identity unavailable")),
        )
        with pytest.raises(LifecycleError, match="Identity unavailable"):
            manager.start(timeout=1)
    assert manager._children
    assert all(child.poll() is not None for child in manager._children.values())


@pytest.mark.parametrize(
    "updates",
    [{"openai_api_key": SecretStr("secret-value\x00invalid")}, {"api_host": "host\x00invalid"}],
)
def test_invalid_text_configuration_is_rejected_before_mutation(tmp_path, updates):
    settings = Settings(_env_file=None, data_dir=tmp_path / "untouched").model_copy(update=updates)
    with pytest.raises(LifecycleError, match="unsupported text") as error:
        ServiceManager(settings)
    assert "secret-value" not in str(error.value)
    assert not settings.data_dir.exists()


def test_unsupported_platform_has_actionable_foreground_fallback(manager, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(LifecycleError, match="foreground"):
        manager.start(timeout=1)


def test_actual_cli_start_restart_stop_round_trip_isolated_postgres(running_manager):
    manager = running_manager
    environment = {**os.environ, **manager.environment}
    results = []
    for action in ("start", "start", "restart", "stop", "stop"):
        completed = subprocess.run(
            [sys.executable, "-m", "org_harness.cli", action, "--timeout", "10"],
            cwd=manager.cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=25,
        )
        assert completed.returncode == 0, completed.stderr
        results.append(json.loads(completed.stdout))
    assert results[0]["services"]["api"]["pid"] == results[1]["services"]["api"]["pid"]
    assert results[2]["services"]["api"]["pid"] != results[0]["services"]["api"]["pid"]
    assert all(result["services"]["worker"]["status"] == "stopped" for result in results[-2:])
