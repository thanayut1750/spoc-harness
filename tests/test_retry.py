"""Failed execution resumes checkpoints without erasing policy or evidence."""

import httpx
import pytest

from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.storage import ConflictError, MemoryStorage, PostgresStorage


async def exercise_retry(storage):
    run = await storage.create_run(
        {
            "user_request": "Build page",
            "constitution": {},
            "limits": {"max_model_calls": 10},
            "model_config": {
                "provider": "configured",
                "model": "same-model",
                "reasoning_effort": "medium",
            },
        }
    )
    run_id = run["run_id"]
    await storage.update_run(
        run_id,
        status="failed",
        error="Execution failed (NotFoundError)",
        model_calls=3,
        tool_calls=2,
        epochs={"direct-1": 4},
        outcomes={"previous": {"approved": True}},
        governance_halt={"kind": "constitution_violation"},
        failure_context={"phase": "graph_execution", "type": "NotFoundError"},
    )
    await storage.begin_operation(
        run_id, "pending-listing", "command", {"command": "pwd && ls -la"}
    )
    result = await storage.command(run_id, "retry", {}, "retry-once")
    assert result == {"run_id": run_id, "status": "queued"}
    assert await storage.command(run_id, "retry", {}, "retry-once") == result
    restored = await storage.get_run(run_id)
    assert restored["error"] is None
    assert restored["failure_context"] is None
    assert restored["retry_count"] == 1
    assert restored["model_calls"] == 3 and restored["tool_calls"] == 2
    assert restored["epochs"] == {"direct-1": 4}
    assert restored["outcomes"] == {"previous": {"approved": True}}
    assert restored["model_config"]["model"] == "same-model"
    assert restored["governance_halt"] == {"kind": "constitution_violation"}
    assert restored["failure_history"][0]["error"] == "Execution failed (NotFoundError)"
    assert restored["failure_history"][0]["failure_context"]["phase"] == "graph_execution"
    assert (await storage.uncertain_operations(run_id))[0]["operation_id"] == "pending-listing"
    with pytest.raises(ConflictError):
        await storage.command(run_id, "retry", {})
    assert (await storage.claim_job("recovery-worker"))["run_id"] == run_id


async def test_retry_preserves_work_limits_governance_and_uncertain_operations():
    await exercise_retry(MemoryStorage())


@pytest.mark.parametrize(
    "status", ["queued", "running", "paused", "review", "cancelled", "succeeded"]
)
async def test_retry_never_restarts_non_failed_runs(status):
    storage = MemoryStorage()
    run = await storage.create_run({"user_request": "one"})
    await storage.update_run(run["run_id"], status=status)
    with pytest.raises(ConflictError):
        await storage.command(run["run_id"], "retry", {})
    assert (await storage.get_run(run["run_id"]))["status"] == status


async def test_api_retry_same_run_is_idempotent(tmp_path):
    storage = MemoryStorage()
    app = create_app(Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path), storage)
    run = await storage.create_run({"user_request": "Build"})
    await storage.update_run(
        run["run_id"], status="failed", error="Execution failed (NotFoundError)"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        path = f"/api/runs/{run['run_id']}/retry"
        response = await client.post(path, headers={"Idempotency-Key": "retry"})
        assert response.status_code == 202
        assert (
            await client.post(path, headers={"Idempotency-Key": "retry"})
        ).json() == response.json()
        assert (await client.post(path)).status_code == 409
        assert (
            await client.post(path, headers={"Origin": "https://untrusted.invalid"})
        ).status_code == 403
    assert len(await storage.list_runs()) == 1
    assert (await storage.get_run(run["run_id"]))["failure_history"]


@pytest.mark.integration
async def test_postgres_retry_is_transactional_and_preserves_uncertainty(postgres_url):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        await exercise_retry(storage)
    finally:
        await storage.close()
