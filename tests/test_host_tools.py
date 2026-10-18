import asyncio
from pathlib import Path

import pytest

from org_harness.models import EscalationSignal, RunCreate
from org_harness.storage import MemoryStorage
from org_harness.tools import Artifacts, HostTools


async def make_host(tmp_path):
    storage = MemoryStorage()
    run = await storage.create_run(
        RunCreate(user_request="Test host tools").model_dump(mode="json")
    )
    artifacts = Artifacts(storage, tmp_path, run["run_id"])

    async def emit(*args, **kwargs):
        pass

    host = HostTools(
        storage,
        artifacts,
        run,
        kr_id="kr-1",
        department="engineering",
        epoch=0,
        role="backend_coder",
        emit=emit,
    )
    return storage, run, artifacts, host


async def test_completed_command_is_not_reexecuted(tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path)
    command = "echo executed >> marker.txt; cat marker.txt"
    first = await host.run_command("call-1", command)
    second = await host.run_command("call-1", command)
    assert first == second
    assert (host.workspace / "marker.txt").read_text().splitlines() == ["executed"]
    assert len(await storage.list_artifacts(run["run_id"])) == 2


async def test_unknown_command_requires_review(tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path)
    operation = host.operation_id("call-1", "run_command")
    await storage.begin_operation(
        run["run_id"], operation, "command", {"command": "echo hello", "cwd": None, "timeout": 300}
    )
    with pytest.raises(EscalationSignal, match="Review interrupted command"):
        await host.run_command("call-1", "echo hello")
    await storage.complete_operation(operation, None, status="retry_approved")
    result = await host.run_command("call-1", "echo hello")
    assert result["stdout"].strip() == "hello"


async def test_cancel_terminates_host_process(tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path)
    command = asyncio.create_task(host.run_command("call-1", "sleep 30"))
    await asyncio.sleep(0.15)
    await storage.command(run["run_id"], "cancel", {})
    with pytest.raises(EscalationSignal) as result:
        await asyncio.wait_for(command, 3)
    assert result.value.kind == "cancelled"


async def test_timeout_and_artifact_integrity(tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path)
    result = await host.run_command("call-1", "sleep 30", timeout=1)
    assert result["exit_code"] == 124
    artifact = await artifacts.save("source.py", "print('hello')", kr_id="kr-1")
    metadata, content = await artifacts.read(artifact["artifact_id"])
    assert content == "print('hello')"
    Path(metadata["path"]).write_text("changed")
    with pytest.raises(ValueError, match="evidence record"):
        await artifacts.read(artifact["artifact_id"])


async def test_cached_operation_rejects_a_different_request(tmp_path):
    _, _, _, host = await make_host(tmp_path)
    await host.run_command("reused-id", "true")
    with pytest.raises(EscalationSignal) as error:
        await host.run_command("reused-id", "false")
    assert error.value.kind == "operation_conflict"


async def test_reused_provider_ids_are_isolated_between_work_packages_and_attempts(tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path)
    command = "echo executed >> attempts.txt"
    await host.run_command("provider-id", command)
    for work_package, attempt in [("second-package", 0), ("second-package", 1)]:
        other = HostTools(
            storage,
            artifacts,
            run,
            kr_id="kr-1",
            department="engineering",
            epoch=0,
            role="backend_coder",
            emit=host.emit,
            work_package_id=work_package,
            attempt=attempt,
        )
        await other.run_command("provider-id", command)
        await other.run_command("provider-id", command)  # Same attempt is a replay.
    assert (host.workspace / "attempts.txt").read_text().splitlines() == ["executed"] * 3
