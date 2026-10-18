"""SIGINT recovery uses only a disposable database, process group and workspace."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from org_harness.config import Settings
from org_harness.runtime import runtime_config
from org_harness.storage import PostgresStorage
from org_harness.tools import Artifacts, HostTools
from org_harness.worker import Worker, migrate

_CHECKPOINT_REPORT = "Saved before the interrupted command."


class RecoveryState(TypedDict, total=False):
    run_id: str
    user_request: str
    constitution: dict
    status: str
    report: str


def recovery_graph(services, *, checkpointer=None, store=None):
    async def command(state):
        async def emit(*args, **kwargs):
            pass

        host = HostTools(
            services.storage,
            Artifacts(services.storage, services.settings.data_dir, state["run_id"]),
            services.run,
            kr_id="shutdown-test",
            department="engineering",
            epoch=0,
            role="backend_coder",
            emit=emit,
        )
        # Start the child before publishing its identity, so cleanup can verify
        # both owned processes even if the group leader exits first.
        await host.run_command(
            "interrupted-command",
            "sleep 30 & command_child=$!; "
            'printf "%s %s\\n" "$BASHPID" "$command_child" >> child.pid; '
            'wait "$command_child"',
        )
        return {"status": "completed", "report": "Command unexpectedly finished."}

    return (
        StateGraph(RecoveryState)
        .add_node("save", lambda _: {"status": "running", "report": _CHECKPOINT_REPORT})
        .add_node("command", command)
        .add_edge(START, "save")
        .add_edge("save", "command")
        .add_edge("command", END)
        .compile(checkpointer=checkpointer, store=store)
    )


async def child_worker() -> None:
    settings = Settings(
        _env_file=None,
        database_url=os.environ["SPOC_RECOVERY_TEST_DATABASE"],
        data_dir=Path(os.environ["SPOC_RECOVERY_TEST_DATA"]),
        harness_test_mode=True,
        storage_backend="postgres",
    )

    def services_factory(settings, storage, run):
        async def close():
            (settings.data_dir / "services-closed").write_text("closed")

        return SimpleNamespace(settings=settings, storage=storage, run=run, close=close)

    await Worker(
        settings, services_factory=services_factory, graph_factory=recovery_graph
    ).run_forever()


def process_identity(pid: int) -> tuple[str, int, str] | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[0], int(fields[2]), fields[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def active_group_members(group: int) -> set[int]:
    active = set()
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            identity = process_identity(int(entry.name))
            if identity and identity[1] == group and identity[0] != "Z":
                active.add(int(entry.name))
    return active


async def wait_until(predicate, *, timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


@pytest.mark.integration
async def test_worker_sigint_preserves_checkpoint_and_requires_review_before_command_recovery(
    tmp_path, postgres_url
):
    settings = Settings(
        _env_file=None,
        database_url=postgres_url,
        data_dir=tmp_path / "recovery",
        harness_test_mode=True,
    )
    await migrate(settings)
    storage = PostgresStorage(postgres_url)
    await storage.open()
    child = None
    group = None
    owned_command_processes = {}
    log = None
    interrupt_sent = False
    try:
        async with asyncio.timeout(15):
            run = await storage.create_run(
                {"user_request": "Isolated shutdown recovery", "constitution": {}}
            )
            settings.data_dir.mkdir(parents=True)
            log = (settings.data_dir / "test-worker.log").open("wb")
            child = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--worker-child"],
                cwd=Path(__file__).resolve().parents[1],
                env={
                    **os.environ,
                    "SPOC_RECOVERY_TEST_DATABASE": postgres_url,
                    "SPOC_RECOVERY_TEST_DATA": str(settings.data_dir),
                },
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            marker = (
                settings.data_dir
                / "workspaces"
                / run["run_id"]
                / "shutdown-test"
                / "0"
                / "child.pid"
            )
            await wait_until(marker.exists, timeout=8)
            command_pids = [int(value) for value in marker.read_text().split()]
            assert len(command_pids) == 2
            group = command_pids[0]
            for pid in command_pids:
                identity = process_identity(pid)
                assert identity is not None and identity[1] == group
                owned_command_processes[pid] = identity[2]
            pending = await storage.uncertain_operations(run["run_id"])
            assert len(pending) == 1
            operation_id = pending[0]["operation_id"]

            child.send_signal(signal.SIGINT)
            interrupt_sent = True
            await wait_until(lambda: child.poll() is not None)
            assert child.returncode == 0
            assert (settings.data_dir / "services-closed").read_text() == "closed"
            await wait_until(lambda: not active_group_members(group))
            interrupted = await storage.get_run(run["run_id"])
            assert interrupted["status"] == "running"
            assert not interrupted.get("cancel_requested")
            assert interrupted["report"] == _CHECKPOINT_REPORT
            assert (await storage.get_operation(operation_id))["status"] == "pending"
            async with storage.pool.connection() as connection:
                job = await (
                    await connection.execute(
                        "SELECT owner,lease_until FROM harness_jobs WHERE run_id=%s",
                        (run["run_id"],),
                    )
                ).fetchone()
                assert job == {"owner": None, "lease_until": None}
            async with storage.worker_lock() as acquired:
                assert acquired is not None

            async with AsyncPostgresSaver.from_conn_string(postgres_url) as saver:
                graph = recovery_graph(SimpleNamespace(), checkpointer=saver)
                before = await graph.aget_state(runtime_config(run["run_id"]))
                assert before.values["report"] == _CHECKPOINT_REPORT
                assert before.next == ("command",)

                def forbidden(*args, **kwargs):
                    raise AssertionError("Pending-command recovery must precede services and graph")

                replacement = Worker(
                    settings,
                    storage,
                    services_factory=forbidden,
                    graph_factory=forbidden,
                    checkpointer=saver,
                )
                assert await replacement.run_once()
                review = await storage.get_run(run["run_id"])
                assert review["status"] == "review"
                assert review["review"]["kind"] == "unknown_operation"
                assert review["review"]["operation_id"] == operation_id
                assert review["report"] == _CHECKPOINT_REPORT
                assert await storage.uncertain_operations(run["run_id"]) == pending
                after = await graph.aget_state(runtime_config(run["run_id"]))
                assert after.config == before.config
                assert after.next == before.next
                assert marker.read_text().splitlines() == [" ".join(map(str, command_pids))]
                assert not active_group_members(group)
    finally:
        if child is not None and child.poll() is None:
            if not interrupt_sent:
                child.send_signal(signal.SIGINT)
            try:
                await asyncio.to_thread(child.wait, timeout=3)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    await asyncio.to_thread(child.wait, timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    await asyncio.to_thread(child.wait, timeout=3)
        # Signal only a group that still contains a process with its original
        # recorded start time, rather than a recycled PID from another process.
        if group is not None and any(
            (identity := process_identity(pid))
            and identity[1] == group
            and identity[2] == started
            and identity[0] != "Z"
            for pid, started in owned_command_processes.items()
        ):
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if log is not None:
            log.close()
        await storage.close()


if __name__ == "__main__" and sys.argv[1:] == ["--worker-child"]:
    try:
        asyncio.run(child_worker())
    except KeyboardInterrupt:
        pass
