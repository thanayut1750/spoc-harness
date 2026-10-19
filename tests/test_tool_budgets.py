"""Tool limits are independently configurable without discarding saved execution."""

import asyncio
import copy

import httpx
import pytest
from pydantic import ValidationError

from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.models import (
    ModelCallBudget,
    ModelCallBudgetUpdate,
    RunBudgetUpdate,
    RunCreate,
    RunLimits,
)
from org_harness.storage import BudgetExceeded, MemoryStorage, PostgresStorage


@pytest.mark.parametrize("limit", [None, 1, 200, 100000])
def test_tool_budget_contracts_share_default_null_and_finite_bounds(limit):
    assert ModelCallBudget(max_tool_calls=limit).max_tool_calls == limit
    assert (
        ModelCallBudgetUpdate(
            max_model_calls=100, worker_model_calls=12, max_tool_calls=limit
        ).max_tool_calls
        == limit
    )
    assert RunLimits(max_tool_calls=limit).max_tool_calls == limit
    assert RunBudgetUpdate(max_tool_calls=limit).model_dump(exclude_unset=True) == {
        "max_tool_calls": limit
    }
    assert ModelCallBudget().max_tool_calls == RunLimits().max_tool_calls == 200


@pytest.mark.parametrize("invalid", [0, -1, 100001, 1.5, "unlimited"])
def test_tool_budget_invalid_values_and_empty_updates_are_rejected(invalid):
    for schema in (RunLimits, ModelCallBudget, RunBudgetUpdate):
        with pytest.raises(ValidationError):
            schema(max_tool_calls=invalid)
    with pytest.raises(ValidationError):
        RunBudgetUpdate()


async def exercise_workspace_tools(storage, client):
    old_settings = {"max_model_calls": None, "worker_model_calls": None}
    await storage.save_setting("model_call_budget", old_settings)
    assert (await client.get("/api/settings")).json()["model_call_budget"] == {
        **old_settings,
        "max_tool_calls": 200,
    }
    before = await client.post("/api/runs", json={"user_request": "Existing mission keeps its cap"})
    before_run = await storage.get_run(before.json()["run_id"])
    unlimited = {**old_settings, "max_tool_calls": None}
    response = await client.put("/api/settings/budgets", json=unlimited)
    assert response.status_code == 200
    assert response.json()["model_call_budget"] == unlimited
    assert await storage.get_setting("model_call_budget") == unlimited
    # A pre-feature client must not silently restore a hidden cap of 200.
    legacy_client = {"max_model_calls": 500, "worker_model_calls": 17}
    saved = await client.put("/api/settings/budgets", json=legacy_client)
    assert saved.json()["model_call_budget"] == {**legacy_client, "max_tool_calls": None}
    inherited = await client.post("/api/runs", json={"user_request": "Inherited unlimited tools"})
    assert (await storage.get_run(inherited.json()["run_id"]))["limits"]["max_tool_calls"] is None
    explicit = await client.post(
        "/api/runs", json={"user_request": "Explicit finite tools", "limits": {"max_tool_calls": 3}}
    )
    assert (await storage.get_run(explicit.json()["run_id"]))["limits"]["max_tool_calls"] == 3
    await client.put("/api/settings/budgets", json={**legacy_client, "max_tool_calls": 700})
    explicit_null = await client.post(
        "/api/runs",
        json={"user_request": "Explicit unlimited tools", "limits": {"max_tool_calls": None}},
    )
    assert (await storage.get_run(explicit_null.json()["run_id"]))["limits"][
        "max_tool_calls"
    ] is None
    assert await storage.get_run(before_run["run_id"]) == before_run
    for invalid in (0, 100001, "unlimited"):
        assert (
            await client.put(
                "/api/settings/budgets", json={**legacy_client, "max_tool_calls": invalid}
            )
        ).status_code == 422
    reset = await client.post("/api/regenesis", json={"confirmation": "REGENESIS"})
    assert reset.status_code == 200
    assert reset.json()["settings"]["model_call_budget"] == ModelCallBudget().model_dump(
        mode="json"
    )
    await client.put("/api/settings/budgets", json=unlimited)


async def exercise_tool_fingerprints(storage, client):
    # These receipts predate the tool setting: v2 only tracked model-field
    # presence, while the first format hashed the expanded request directly.
    for version in (None, 2):
        for value in ("omitted", 200, 77):
            request = {"user_request": f"Old receipt {version} {value}"}
            if value != "omitted":
                request["limits"] = {"max_tool_calls": value}
            body = RunCreate.model_validate(request)
            normalized = body.model_dump(mode="json", by_alias=True, exclude_none=True)
            receipt = (
                normalized
                if version is None
                else {"fingerprint_version": 2, "request": normalized, "explicit_budget_fields": []}
            )
            key = f"old-{version}-{value}"
            old = await storage.create_run(normalized, key, request_payload=receipt)
            replay = await client.post("/api/runs", json=request, headers={"Idempotency-Key": key})
            assert replay.status_code == 202 and replay.json()["run_id"] == old["run_id"]
            assert await storage.get_run(old["run_id"]) == old
            changed = {**request, "limits": {"max_tool_calls": None}}
            assert (
                await client.post("/api/runs", json=changed, headers={"Idempotency-Key": key})
            ).status_code == 409
    variants = [None, {}, {"max_tool_calls": None}, {"max_tool_calls": 200}, {"max_tool_calls": 17}]
    for index, limits in enumerate(variants):
        request = {"user_request": f"Distinct tool intent {index}"}
        if limits is not None:
            request["limits"] = limits
        headers = {"Idempotency-Key": f"v3-tools-{index}"}
        first = await client.post("/api/runs", json=request, headers=headers)
        assert first.status_code == 202
        original = await storage.get_run(first.json()["run_id"])
        await client.put(
            "/api/settings/budgets",
            json={"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": 900},
        )
        assert (
            await client.post("/api/runs", json=request, headers=headers)
        ).json() == first.json()
        assert await storage.get_run(original["run_id"]) == original
        for other in variants:
            if (limits in (None, {}) and other in (None, {})) or other == limits:
                continue
            changed = {"user_request": request["user_request"]}
            if other is not None:
                changed["limits"] = other
            assert (
                await client.post("/api/runs", json=changed, headers=headers)
            ).status_code == 409


async def exercise_stopped_run_budget_update(storage, client):
    request = {
        "user_request": "Keep the current interrupted command and evidence",
        "limits": {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": 200},
    }
    headers = {"Idempotency-Key": "immutable-creation"}
    created = await client.post("/api/runs", json=request, headers=headers)
    run_id = created.json()["run_id"]
    original = await storage.get_run(run_id)
    await storage.reserve_budget(run_id, "model", 110)
    await storage.reserve_budget(run_id, "tool", 200)
    review = {
        "kind": "unknown_operation",
        "interrupt_id": "unchanged-review",
        "operation_id": "pending-command",
        "reason": "The interrupted command needs a decision",
    }
    await storage.update_run(
        run_id,
        status="review",
        review=review,
        epochs={"KR1": 3},
        outcomes={},
        progress={"KR1": "escalated"},
    )
    operation = await storage.begin_operation(
        run_id, "pending-command", "command", {"command": "retain this pending operation"}
    )
    artifact = await storage.register_artifact(
        {
            "artifact_id": "preserved-artifact",
            "run_id": run_id,
            "name": "output.txt",
            "kind": "text",
            "path": "not-read-by-this-test",
        }
    )
    before = await storage.get_run(run_id)
    path = f"/api/runs/{run_id}/budgets"
    budget_headers = {"Idempotency-Key": "remove-current-tool-cap"}
    responses = await asyncio.gather(
        *(client.put(path, json={"max_tool_calls": None}, headers=budget_headers) for _ in range(5))
    )
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json() == responses[0].json() for response in responses)
    updated = await storage.get_run(run_id)
    assert updated["limits"] == {**before["limits"], "max_tool_calls": None}
    assert updated["original_limits"] == original["limits"]
    assert len(updated["budget_history"]) == 1
    assert updated["budget_history"][0]["tool_calls"] == 200
    for field, value in before.items():
        if field not in {"limits", "updated_at"}:
            assert updated[field] == value
    assert await storage.get_operation(operation["operation_id"]) == operation
    assert await storage.list_artifacts(run_id) == [artifact]
    assert (await storage.uncertain_operations(run_id)) == [operation]
    assert responses[0].json()["review"]["interrupt_id"] == review["interrupt_id"]
    assert responses[0].json()["limits"]["max_tool_calls"] is None
    assert (await client.post("/api/runs", json=request, headers=headers)).json() == created.json()
    assert (await storage.get_run(run_id))["limits"]["max_tool_calls"] is None
    assert await storage.reserve_budget(run_id, "tool") == 201
    # Cached no-op replays remain available even while a worker owns the guard.
    async with storage.worker_lock() as guard:
        assert guard
        assert (
            await client.put(path, json={"max_tool_calls": None}, headers=budget_headers)
        ).status_code == 200
        before_busy = await storage.get_run(run_id)
        assert (await client.put(path, json={"max_tool_calls": 700})).status_code == 409
        assert await storage.get_run(run_id) == before_busy
    assert (
        await client.put(path, json={"max_tool_calls": 700}, headers=budget_headers)
    ).status_code == 409
    assert (await client.put(path, json={})).status_code == 422
    assert (await client.put(path, json={"command_timeout": 700})).status_code == 422
    assert (await client.put(path, json={"max_tool_calls": 100001})).status_code == 422
    for status in ("paused", "review", "failed"):
        await storage.update_run(run_id, status=status)
        response = await client.put(path, json={"worker_model_calls": None})
        assert response.status_code == 200
        current = await storage.get_run(run_id)
        assert current["status"] == status and current["review"] == review
        assert current["tool_calls"] == 201 and current["model_calls"] == 110
        assert current["limits"]["max_tool_calls"] is None
    for status in ("queued", "running", "succeeded", "cancelled"):
        await storage.update_run(run_id, status=status)
        snapshot = await storage.get_run(run_id)
        assert (await client.put(path, json={"max_tool_calls": 800})).status_code == 409
        assert await storage.get_run(run_id) == snapshot
    cancelled_request = await storage.create_run({"user_request": "Cancellation wins"})
    await storage.update_run(cancelled_request["run_id"], status="review", cancel_requested=True)
    assert (
        await client.put(
            f"/api/runs/{cancelled_request['run_id']}/budgets", json={"max_tool_calls": None}
        )
    ).status_code == 409
    return run_id


async def exercise_atomic_tool_usage(storage):
    run = await storage.create_run(
        RunCreate(
            user_request="Unlimited tool calls still count",
            limits=RunLimits(max_tool_calls=None, max_model_calls=1),
        ).model_dump(mode="json")
    )
    values = await asyncio.gather(
        *(storage.reserve_budget(run["run_id"], "tool") for _ in range(211))
    )
    assert sorted(values) == list(range(1, 212))
    assert (await storage.get_run(run["run_id"]))["tool_calls"] == 211
    with pytest.raises(BudgetExceeded):
        await storage.reserve_budget(run["run_id"], "model", 2)
    finite = await storage.create_run(
        RunCreate(
            user_request="Finite tools still stop", limits=RunLimits(max_tool_calls=2)
        ).model_dump(mode="json")
    )
    outcomes = await asyncio.gather(
        *(storage.reserve_budget(finite["run_id"], "tool") for _ in range(5)),
        return_exceptions=True,
    )
    assert sorted(value for value in outcomes if isinstance(value, int)) == [1, 2]
    assert sum(isinstance(value, BudgetExceeded) for value in outcomes) == 3
    return run["run_id"]


async def exercise_direct_budget_command_replay(storage):
    run = await storage.create_run(
        RunCreate(user_request="Concurrent budget command").model_dump(mode="json")
    )
    await storage.update_run(run["run_id"], status="paused")
    results = await asyncio.gather(
        *(
            storage.command(
                run["run_id"], "budgets", {"max_tool_calls": None}, "direct-budget-update"
            )
            for _ in range(6)
        )
    )
    assert all(result == results[0] for result in results)
    current = await storage.get_run(run["run_id"])
    assert current["status"] == "paused" and current["limits"]["max_tool_calls"] is None
    assert len(current["budget_history"]) == 1
    assert current["original_limits"] == run["limits"]


async def exercise_all_tools(storage, tmp_path):
    settings = Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, storage)), base_url="http://test"
    ) as client:
        await exercise_workspace_tools(storage, client)
        await exercise_tool_fingerprints(storage, client)
        updated_id = await exercise_stopped_run_budget_update(storage, client)
        counted_id = await exercise_atomic_tool_usage(storage)
        await exercise_direct_budget_command_replay(storage)
        return copy.deepcopy(await storage.get_run(updated_id)), counted_id


async def test_memory_tool_settings_create_replay_existing_run_update_and_atomic_usage(tmp_path):
    await exercise_all_tools(MemoryStorage(), tmp_path)


@pytest.mark.integration
async def test_postgres_tool_settings_and_stopped_mission_updates_survive_reopen(
    postgres_url, tmp_path
):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        snapshot, counted_id = await exercise_all_tools(storage, tmp_path)
    finally:
        await storage.close()
    reopened = PostgresStorage(postgres_url)
    await reopened.open()
    try:
        assert await reopened.get_run(snapshot["run_id"]) == snapshot
        assert (await reopened.get_setting("model_call_budget"))["max_tool_calls"] == 900
        assert await reopened.reserve_budget(counted_id, "tool") == 212
    finally:
        await reopened.close()
