"""Real subprocess interruption, independent receipts and replay without repeated effects."""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

import pytest

from org_harness.autonomy import AutonomousCheckpointYield
from org_harness.command_runner import atomic_json, process_identity, signal_process
from org_harness.config import Settings
from org_harness.models import EscalationSignal, RunCreate
from org_harness.storage import MemoryStorage, fingerprint
from org_harness.tools import (
    Artifacts,
    HostTools,
    reconcile_pending_commands,
    stop_run_command_processes,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux pidfd recovery")
UNLIMITED = {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None}


async def noop(*args, **kwargs):
    pass


async def host_fixture(tmp_path, *, limits=None, storage=None):
    storage = storage or MemoryStorage()
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", openai_api_key="fixture-key")
    run = await storage.create_run(
        RunCreate(user_request="Finish the assignment", limits=limits or UNLIMITED).model_dump(
            mode="json"
        )
    )
    artifacts = Artifacts(storage, settings.data_dir, run["run_id"])
    host = HostTools(
        storage,
        artifacts,
        run,
        kr_id="kr",
        department="engineering",
        epoch=0,
        role="specialist:test:bounded",
        emit=noop,
        work_package_id="work",
    )
    return settings, storage, run, artifacts, host


async def wait_until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), 10)


class RestartableStorage(MemoryStorage):
    """Persist the real journal interface across a disposable harness process."""

    def __init__(self, path):
        super().__init__()
        self.fixture_path = Path(path)
        if self.fixture_path.exists():
            state = json.loads(self.fixture_path.read_text())
            self.runs, self.operations, self.artifacts = (
                state[key] for key in ("runs", "operations", "artifacts")
            )

    def persist(self):
        atomic_json(
            self.fixture_path,
            {
                "runs": self.runs,
                "operations": self.operations,
                "artifacts": self.artifacts,
            },
        )

    async def create_run(self, *args, **kwargs):
        result = await super().create_run(*args, **kwargs)
        self.persist()
        return result

    async def reserve_budget(self, *args, **kwargs):
        result = await super().reserve_budget(*args, **kwargs)
        self.persist()
        return result

    async def begin_operation(self, *args, **kwargs):
        result = await super().begin_operation(*args, **kwargs)
        self.persist()
        return result

    async def complete_operation(self, *args, **kwargs):
        await super().complete_operation(*args, **kwargs)
        self.persist()

    async def register_artifact(self, *args, **kwargs):
        result = await super().register_artifact(*args, **kwargs)
        self.persist()
        return result


async def child_harness(storage_path, data_dir, timeout):
    storage = RestartableStorage(storage_path)
    run = (await storage.list_runs())[0]
    host = HostTools(
        storage,
        Artifacts(storage, Path(data_dir), run["run_id"]),
        run,
        kr_id="kr",
        department="engineering",
        epoch=0,
        role="specialist:test:bounded",
        emit=noop,
        work_package_id="work",
    )
    await host.run_command(
        "command", "echo once >> effect.txt; echo started; sleep 30", timeout=timeout
    )


async def test_completed_autonomous_command_has_durable_result_and_replays_without_charge(tmp_path):
    settings, storage, run, artifacts, host = await host_fixture(tmp_path)
    command = "echo once >> effect.txt; cat effect.txt"
    result = await host.run_command("command", command)
    assert result["exit_code"] == 0
    assert result["execution_stopped"] is True
    assert not result["interrupted"] and not result["effects_uncertain"]
    assert result["stdout"] == "once\n"
    assert await host.run_command("command", command) == result
    assert (host.workspace / "effect.txt").read_text() == "once\n"
    assert (await storage.get_run(run["run_id"]))["tool_calls"] == 1
    assert not await reconcile_pending_commands(settings, storage, run)
    operation = host.operation_id("command", "run_command")
    manifest = json.loads((artifacts.root / "operations" / f"{operation}.process.json").read_text())
    assert manifest["process"]["pid"] == manifest["process"]["session"]


async def test_controlled_cancellation_records_interruption_after_stopping_process(tmp_path):
    settings, storage, run, artifacts, host = await host_fixture(tmp_path)
    command = "echo once >> effect.txt; echo running; sleep 30"
    task = asyncio.create_task(host.run_command("command", command))
    try:
        await wait_until(
            lambda: (
                (host.workspace / "effect.txt").exists()
                and (host.workspace / "effect.txt").read_text() == "once\n"
            )
        )
        operation_id = host.operation_id("command", "run_command")
        manifest = json.loads(
            (artifacts.root / "operations" / f"{operation_id}.process.json").read_text()
        )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        operation = await storage.get_operation(operation_id)
        assert operation["status"] == "done"
        result = operation["result"]
        assert result["exit_code"] != 0 and result["interrupted"]
        assert result["execution_stopped"] is True and result["effects_uncertain"]
        assert result["stdout"].strip() == "running"
        identity = process_identity(manifest["process"]["pid"])
        assert identity is None or identity["state"] == "Z"
        assert not await storage.uncertain_operations(run["run_id"])
        assert await host.run_command("command", command) == result
        assert (host.workspace / "effect.txt").read_text() == "once\n"
        assert (await storage.get_run(run["run_id"]))["tool_calls"] == 1
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("finite_key", ["all", *UNLIMITED])
async def test_finite_mode_keeps_existing_review_for_interrupted_commands(tmp_path, finite_key):
    defaults = {"max_model_calls": 100, "worker_model_calls": 12, "max_tool_calls": 200}
    settings, storage, run, _, host = await host_fixture(
        tmp_path,
        limits=defaults if finite_key == "all" else {**UNLIMITED, finite_key: defaults[finite_key]},
    )
    operation_id = host.operation_id("legacy", "run_command")
    request = {"command": "echo never >> effect.txt", "cwd": None, "timeout": 300}
    await storage.begin_operation(run["run_id"], operation_id, "command", request)
    assert await reconcile_pending_commands(settings, storage, run) == []
    with pytest.raises(EscalationSignal) as error:
        await host.run_command("legacy", request["command"])
    assert error.value.kind == "unknown_operation"
    assert (await storage.get_operation(operation_id))["status"] == "pending"
    assert not (host.workspace / "effect.txt").exists()


@pytest.mark.parametrize("timeout", [1, 300])
async def test_hard_worker_crash_recovers_independent_supervisor_receipt_without_repeating_effect(
    tmp_path, timeout
):
    state_path = tmp_path / "restart.json"
    settings, storage, run, artifacts, host = await host_fixture(
        tmp_path, storage=RestartableStorage(state_path)
    )
    code = (
        "import asyncio,sys; from test_autonomous_commands import child_harness; "
        "asyncio.run(child_harness(sys.argv[1],sys.argv[2],int(sys.argv[3])))"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).parent) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    harness = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        code,
        str(state_path),
        str(settings.data_dir),
        str(timeout),
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await wait_until(
            lambda: (
                (
                    (host.workspace / "effect.txt").exists()
                    and (host.workspace / "effect.txt").read_text() == "once\n"
                )
                or harness.returncode is not None
            )
        )
        assert (host.workspace / "effect.txt").read_text() == "once\n"
        operation_id = host.operation_id("command", "run_command")
        path = artifacts.root / "operations" / f"{operation_id}.process.json"
        manifest = json.loads(path.read_text())
        harness.kill()
        await harness.wait()
        assert harness.returncode == -signal.SIGKILL
        if timeout == 1:
            # The independent supervisor must enforce the command deadline even
            # while no harness worker exists to monitor it.
            await wait_until(lambda: path.with_suffix(".result.json").exists())
        restarted = RestartableStorage(state_path)
        fresh_run = await restarted.get_run(run["run_id"])
        assert (await restarted.get_operation(operation_id))["status"] == "pending"
        recovered = await reconcile_pending_commands(settings, restarted, fresh_run)
        assert len(recovered) == 1 and recovered[0]["operation_id"] == operation_id
        result = recovered[0]["result"]
        assert result["exit_code"] != 0 and result["effects_uncertain"]
        assert result["execution_stopped"] is True
        assert result["timed_out"] is (timeout == 1)
        assert result["stdout"].strip() == "started"
        identity = process_identity(manifest["process"]["pid"])
        assert identity is None or identity["state"] == "Z"
        replacement_host = HostTools(
            restarted,
            Artifacts(restarted, settings.data_dir, run["run_id"]),
            fresh_run,
            kr_id="kr",
            department="engineering",
            epoch=0,
            role=host.role,
            emit=noop,
            work_package_id="work",
        )
        assert (
            await replacement_host.run_command(
                "command",
                "echo once >> effect.txt; echo started; sleep 30",
                timeout=timeout,
            )
            == result
        )
        assert (host.workspace / "effect.txt").read_text() == "once\n"
        assert (await restarted.get_run(run["run_id"]))["tool_calls"] == 1
        assert not await restarted.uncertain_operations(run["run_id"])
        assert await reconcile_pending_commands(settings, restarted, fresh_run) == []
        receipts = [
            item
            for item in await restarted.list_artifacts(run["run_id"])
            if item["kind"] == "command_result"
        ]
        assert len(receipts) == 1 and receipts[0]["scope"] == host.scope
    finally:
        if harness.returncode is None:
            harness.kill()
            await harness.wait()
        # Always reconcile the owned disposable command, including assertion
        # failures, so the test cannot leave an orphan subprocess behind.
        restarted = RestartableStorage(state_path)
        await reconcile_pending_commands(
            settings, restarted, await restarted.get_run(run["run_id"])
        )


async def test_legacy_unknown_command_becomes_truthful_receipt_without_signal_or_replay(
    tmp_path, monkeypatch
):
    settings, storage, run, _, host = await host_fixture(tmp_path)
    operation_id = host.operation_id("legacy", "run_command")
    command = "echo never >> effect.txt"
    await storage.begin_operation(
        run["run_id"], operation_id, "command", {"command": command, "cwd": None, "timeout": 300}
    )
    signals = []
    monkeypatch.setattr("org_harness.tools.signal_process", lambda *args: signals.append(args))
    results = await reconcile_pending_commands(settings, storage, run)
    result = results[0]["result"]
    assert result["exit_code"] == 125 and result["interrupted"] and result["effects_uncertain"]
    assert result["execution_stopped"] is False and result["process_state"] == "unverified"
    assert "Inspect existing files" in result["recovery_guidance"]
    assert "never authorizes replaying" in result["recovery_guidance"]
    assert await host.run_command("legacy", command) == result
    assert not signals and not (host.workspace / "effect.txt").exists()
    assert (await storage.get_run(run["run_id"]))["tool_calls"] == 0


@pytest.mark.parametrize("wrong_start_time", [False, True])
async def test_unrelated_or_recycled_process_identity_is_never_signalled(
    tmp_path, monkeypatch, wrong_start_time
):
    settings, storage, run, artifacts, host = await host_fixture(tmp_path)
    operation_id = host.operation_id("forged", "run_command")
    command = "echo never >> effect.txt"
    request = {"command": command, "cwd": None, "timeout": 300}
    await storage.begin_operation(run["run_id"], operation_id, "command", request)
    unrelated = await asyncio.create_subprocess_exec("sleep", "30", start_new_session=True)
    try:
        identity = process_identity(unrelated.pid)
        if wrong_start_time:
            identity["start_ticks"] += 1
        path = artifacts.root / "operations" / f"{operation_id}.process.json"
        atomic_json(
            path,
            {
                "run_id": run["run_id"],
                "operation_id": operation_id,
                "request_fingerprint": fingerprint(request),
                "command": command,
                "cwd": str(host.workspace),
                "process": identity,
                "token": "not-this-process",
            },
        )
        signals = []
        monkeypatch.setattr("org_harness.tools.signal_process", lambda *args: signals.append(args))
        result = (await reconcile_pending_commands(settings, storage, run))[0]["result"]
        assert result["exit_code"] == 125 and result["execution_stopped"] is False
        assert unrelated.returncode is None and not signals
        assert not (host.workspace / "effect.txt").exists()
        assert await stop_run_command_processes(settings, run) == []
        assert unrelated.returncode is None and not signals
    finally:
        unrelated.terminate()
        await unrelated.wait()


async def test_supervisor_startup_ownership_prevents_premature_replay_or_false_receipt(tmp_path):
    import fcntl

    settings, storage, run, artifacts, host = await host_fixture(tmp_path)
    operation_id = host.operation_id("starting", "run_command")
    request = {"command": "echo never >> effect.txt", "cwd": None, "timeout": 300}
    await storage.begin_operation(run["run_id"], operation_id, "command", request)
    path = artifacts.root / "operations" / f"{operation_id}.process.json"
    atomic_json(
        path,
        {
            "phase": "prepared",
            "run_id": run["run_id"],
            "operation_id": operation_id,
            "request_fingerprint": fingerprint(request),
            "command": request["command"],
            "cwd": str(host.workspace),
        },
    )
    with path.with_suffix(".lock").open("ab") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(AutonomousCheckpointYield):
            await reconcile_pending_commands(settings, storage, run)
        with pytest.raises(AutonomousCheckpointYield):
            await stop_run_command_processes(settings, run)
        assert (await storage.get_operation(operation_id))["status"] == "pending"
        assert not await storage.list_artifacts(run["run_id"])
    result = (await reconcile_pending_commands(settings, storage, run))[0]["result"]
    assert result["exit_code"] != 0
    assert not (host.workspace / "effect.txt").exists()


async def test_reset_cleanup_stops_owned_supervisor_before_managed_files_are_deleted(tmp_path):
    import shutil

    settings, storage, run, artifacts, host = await host_fixture(tmp_path)
    task = asyncio.create_task(host.run_command("reset", "echo once >> effect.txt; sleep 30"))
    try:
        await wait_until(
            lambda: (
                (host.workspace / "effect.txt").exists()
                and (host.workspace / "effect.txt").read_text() == "once\n"
            )
        )
        operation_id = host.operation_id("reset", "run_command")
        manifest = json.loads(
            (artifacts.root / "operations" / f"{operation_id}.process.json").read_text()
        )
        assert await stop_run_command_processes(settings, run) == [operation_id]
        result = await asyncio.wait_for(task, 5)
        assert result["interrupted"] and result["execution_stopped"] and result["exit_code"] != 0
        identity = process_identity(manifest["process"]["pid"])
        assert identity is None or identity["state"] == "Z"
        shutil.rmtree(artifacts.root)
        assert not artifacts.root.exists()
        assert (host.workspace / "effect.txt").read_text() == "once\n"
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_completed_external_effect_survives_journal_write_failure_without_reexecution(
    tmp_path, monkeypatch
):
    settings, storage, run, _, host = await host_fixture(tmp_path)
    complete = storage.complete_operation

    async def unavailable(*_args, **_kwargs):
        raise ConnectionError("Disposable storage unavailable")

    monkeypatch.setattr(storage, "complete_operation", unavailable)
    with pytest.raises(ConnectionError):
        await host.run_command("commit-gap", "echo once >> effect.txt")
    monkeypatch.setattr(storage, "complete_operation", complete)
    recovered = await reconcile_pending_commands(settings, storage, run)
    assert len(recovered) == 1
    result = recovered[0]["result"]
    assert result["exit_code"] == 0 and not result["interrupted"] and result["execution_stopped"]
    assert await host.run_command("commit-gap", "echo once >> effect.txt") == result
    assert (host.workspace / "effect.txt").read_text() == "once\n"
    assert (await storage.get_run(run["run_id"]))["tool_calls"] == 1


async def test_autonomous_command_logs_have_bounded_previews_and_explicit_artifact_truncation(
    tmp_path,
):
    _, storage, run, artifacts, host = await host_fixture(tmp_path)
    result = await host.run_command(
        "large", "python3 -c \"import sys; sys.stdout.write('x' * 2000100)\""
    )
    assert result["exit_code"] == 0
    assert len(result["stdout"]) == 32768
    assert result["stdout_truncated"] and result["stdout_artifact_truncated"]
    assert result["stdout_log_bytes"] == 2000100
    log = next(
        item
        for item in await storage.list_artifacts(run["run_id"])
        if item["kind"] == "command_log"
    )
    assert log["size"] == 2000000
    assert Path(log["path"]).read_bytes() == b"x" * 2000000


async def test_corrupt_terminal_receipt_cannot_claim_success_and_never_replays(tmp_path):
    settings, storage, run, artifacts, host = await host_fixture(tmp_path)
    result = await host.run_command("corrupt", "echo once >> effect.txt")
    operation_id = host.operation_id("corrupt", "run_command")
    path = artifacts.root / "operations" / f"{operation_id}.process.json"
    terminal = json.loads(path.with_suffix(".result.json").read_text())
    terminal.update(interrupted=True, effects_uncertain=True, exit_code=0)
    atomic_json(path.with_suffix(".result.json"), terminal)
    await storage.complete_operation(operation_id, None, status="pending")
    recovered = (await reconcile_pending_commands(settings, storage, run))[0]["result"]
    assert result["exit_code"] == 0 and recovered["exit_code"] == 125
    assert recovered["effects_uncertain"] and not recovered["execution_stopped"]
    assert await host.run_command("corrupt", "echo once >> effect.txt") == recovered
    assert (host.workspace / "effect.txt").read_text() == "once\n"


@pytest.mark.parametrize("finite", [False, True])
@pytest.mark.parametrize("cleanup", ["completion", "cancellation", "reset"])
async def test_detached_descendant_cannot_escape_command_cleanup(tmp_path, cleanup, finite):
    limits = (
        {"max_model_calls": 100, "worker_model_calls": 12, "max_tool_calls": 200}
        if finite
        else UNLIMITED
    )
    settings, storage, run, _, host = await host_fixture(tmp_path, limits=limits)
    source = (
        "import subprocess,pathlib; "
        "p=subprocess.Popen(['sleep','30'],start_new_session=True); "
        "pathlib.Path('detached.pid').write_text(str(p.pid))"
    )
    command = f'python3 -c "{source}"' + ("; sleep 30" if cleanup != "completion" else "")
    task = asyncio.create_task(host.run_command("detach", command))
    identity = None
    try:
        await wait_until(
            lambda: (
                (host.workspace / "detached.pid").exists()
                and (host.workspace / "detached.pid").read_text().isdigit()
            )
        )
        pid = int((host.workspace / "detached.pid").read_text())
        identity = process_identity(pid)
        if cleanup == "cancellation":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            operation = await storage.get_operation(host.operation_id("detach", "run_command"))
            assert operation["status"] == ("pending" if finite else "done")
            if finite:
                with pytest.raises(EscalationSignal) as error:
                    await host.run_command("detach", command)
                assert error.value.kind == "unknown_operation"
        else:
            if cleanup == "reset":
                assert await stop_run_command_processes(settings, run)
            result = await asyncio.wait_for(task, 5)
            assert result["exit_code"] != 0 and result["execution_stopped"]
            assert result["interrupted"] and result["effects_uncertain"]
        remaining = process_identity(pid)
        assert remaining is None or remaining["state"] == "Z"
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if identity is not None:
            signal_process(identity, signal.SIGKILL)


@pytest.mark.parametrize("finite", [False, True])
async def test_command_self_group_signal_does_not_kill_its_receipt_supervisor(tmp_path, finite):
    limits = (
        {"max_model_calls": 100, "worker_model_calls": 12, "max_tool_calls": 200}
        if finite
        else UNLIMITED
    )
    _, storage, run, artifacts, host = await host_fixture(tmp_path, limits=limits)
    result = await host.run_command("self-signal", 'echo self-signal; kill -TERM -- -"$BASHPID"')
    assert result["exit_code"] == -signal.SIGTERM
    assert result["stdout"].strip() == "self-signal"
    assert result["execution_stopped"]
    assert not result["interrupted"]
    assert not await storage.uncertain_operations(run["run_id"])
    saved = [
        item
        for item in await storage.list_artifacts(run["run_id"])
        if item["kind"] == "command_result"
    ]
    assert len(saved) == 1
    _, content = await artifacts.read(saved[0]["artifact_id"], limit=None)
    assert json.loads(content)["exit_code"] == -signal.SIGTERM
