"""Unlimited model budgets preserve explicit intent, snapshots, and atomic usage counters."""

import asyncio

import httpx
import pytest
from pydantic import ValidationError

from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.models import ModelCallBudget, ModelCallBudgetUpdate, RunCreate, RunLimits
from org_harness.storage import BudgetExceeded, MemoryStorage, PostgresStorage


@pytest.mark.parametrize("model_budget", [None, 1, 10000])
@pytest.mark.parametrize("worker_budget", [None, 1, 100])
def test_nullable_model_budget_contracts_share_existing_finite_bounds(model_budget, worker_budget):
    values = {"max_model_calls": model_budget, "worker_model_calls": worker_budget}
    assert ModelCallBudget(**values).model_dump(mode="json") == {**values, "max_tool_calls": 200}
    assert ModelCallBudgetUpdate(**values).model_dump(mode="json") == {
        **values,
        "max_tool_calls": 200,
    }
    assert RunLimits(**values).model_dump(mode="json") == {
        **values,
        "max_tool_calls": 200,
        "command_timeout": 300,
        "worker_timeout": 3600,
    }
    assert ModelCallBudget().model_dump(mode="json") == {
        "max_model_calls": 100,
        "worker_model_calls": 12,
        "max_tool_calls": 200,
    }


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"max_model_calls": None},
        {"worker_model_calls": None},
        {"max_model_calls": -1, "worker_model_calls": None},
        {"max_model_calls": 10001, "worker_model_calls": None},
        {"max_model_calls": None, "worker_model_calls": 101},
        {"max_model_calls": None, "worker_model_calls": 0},
        {"max_model_calls": "unlimited", "worker_model_calls": None},
    ],
)
def test_both_nullable_update_fields_remain_required_and_finite_bounds_remain(invalid):
    with pytest.raises(ValidationError):
        ModelCallBudgetUpdate(**invalid)
    with pytest.raises(ValidationError):
        RunLimits(max_tool_calls=0)


async def exercise_nullable_api(storage, tmp_path):
    settings = Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path)
    app = create_app(settings, storage)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        defaults = {"max_model_calls": 100, "worker_model_calls": 12}
        assert (await client.get("/api/settings")).json()["model_call_budget"] == {
            **defaults,
            "max_tool_calls": 200,
        }
        # Seed the exact pre-null version2 fingerprint, including the finite
        # expanded limits, to prove the submission normalization stays compatible.
        old_runs = []
        for suffix, limits in (("omitted", None), ("finite", {"max_model_calls": 100})):
            request = {"user_request": f"Prior version2 {suffix}"}
            if limits is not None:
                request["limits"] = limits
            body = RunCreate.model_validate(request)
            normalized = body.model_dump(mode="json", by_alias=True, exclude_none=True)
            old_run = await storage.create_run(
                normalized,
                f"prior-{suffix}",
                request_payload={
                    "fingerprint_version": 2,
                    "request": normalized,
                    "explicit_budget_fields": sorted(
                        body.limits.model_fields_set & defaults.keys()
                    ),
                },
            )
            old_runs.append((request, f"prior-{suffix}", old_run))
        both_null = {"max_model_calls": None, "worker_model_calls": None}
        saved = await client.put("/api/settings/budgets", json=both_null)
        assert saved.status_code == 200
        assert saved.json()["model_call_budget"] == {**both_null, "max_tool_calls": 200}
        assert await storage.get_setting("model_call_budget") == {
            **both_null,
            "max_tool_calls": 200,
        }
        inherited_request = {"user_request": "Replay inherited unlimited defaults"}
        inherited_headers = {"Idempotency-Key": "inherited-null-snapshot"}
        inherited = await client.post(
            "/api/runs", json=inherited_request, headers=inherited_headers
        )
        assert inherited.status_code == 202
        snapshots = []
        for request, expected in (
            ({"user_request": "Inherit unlimited"}, both_null),
            ({"user_request": "Empty limits inherit unlimited", "limits": {}}, both_null),
            (
                {"user_request": "Finite global override", "limits": {"max_model_calls": 7}},
                {"max_model_calls": 7, "worker_model_calls": None},
            ),
            (
                {"user_request": "Finite worker override", "limits": {"worker_model_calls": 3}},
                {"max_model_calls": None, "worker_model_calls": 3},
            ),
            ({"user_request": "Explicit finite defaults", "limits": defaults}, defaults),
        ):
            created = await client.post("/api/runs", json=request)
            assert created.status_code == 202
            run = (await client.get(f"/api/runs/{created.json()['run_id']}")).json()
            assert {name: run["limits"][name] for name in defaults} == expected
            assert (
                run["limits"]["max_tool_calls"] == 200 and run["limits"]["worker_timeout"] == 3600
            )
            snapshots.append(run)
        for request, key, old_run in old_runs:
            replay = await client.post("/api/runs", json=request, headers={"Idempotency-Key": key})
            assert replay.status_code == 202 and replay.json()["run_id"] == old_run["run_id"]
            assert (await storage.get_run(old_run["run_id"]))["limits"] == old_run["limits"]

        await client.put(
            "/api/settings/budgets", json={"max_model_calls": 30, "worker_model_calls": 4}
        )
        assert (
            await client.post("/api/runs", json=inherited_request, headers=inherited_headers)
        ).json() == inherited.json()
        assert (await storage.get_run(inherited.json()["run_id"]))["limits"][
            "max_model_calls"
        ] is None
        assert (await storage.get_run(inherited.json()["run_id"]))["limits"][
            "worker_model_calls"
        ] is None
        for limits, expected in (
            ({"max_model_calls": None}, {"max_model_calls": None, "worker_model_calls": 4}),
            ({"worker_model_calls": None}, {"max_model_calls": 30, "worker_model_calls": None}),
            (both_null, both_null),
        ):
            request = {"user_request": f"Explicit null {list(limits)}", "limits": limits}
            key = f"null-{list(limits)}"
            created = await client.post("/api/runs", json=request, headers={"Idempotency-Key": key})
            assert created.status_code == 202
            run = await storage.get_run(created.json()["run_id"])
            assert {name: run["limits"][name] for name in defaults} == expected
            assert (
                await client.post("/api/runs", json=request, headers={"Idempotency-Key": key})
            ).json() == created.json()
            assert (
                await client.post(
                    "/api/runs",
                    json={"user_request": request["user_request"]},
                    headers={"Idempotency-Key": key},
                )
            ).status_code == 409
        omitted = {"user_request": "Omitted is a different intent"}
        headers = {"Idempotency-Key": "omitted-before-null"}
        assert (await client.post("/api/runs", json=omitted, headers=headers)).status_code == 202
        assert (
            await client.post("/api/runs", json={**omitted, "limits": both_null}, headers=headers)
        ).status_code == 409
        for run in snapshots:
            assert (await storage.get_run(run["run_id"]))["limits"] == run["limits"]
        # Tool budgets retain their finite bounds independently of model budgets.
        assert (
            await client.post(
                "/api/runs",
                json={"user_request": "Invalid tools", "limits": {"max_tool_calls": 0}},
            )
        ).status_code == 422
        reset = await client.post("/api/regenesis", json={"confirmation": "REGENESIS"})
        assert reset.status_code == 200 and reset.json()["settings"]["model_call_budget"] == {
            **defaults,
            "max_tool_calls": 200,
        }
        assert await storage.get_setting("model_call_budget") is None
        await client.put("/api/settings/budgets", json=both_null)
        created = await client.post("/api/runs", json={"user_request": "Persist unlimited"})
        run = await storage.get_run(created.json()["run_id"])
        assert {name: run["limits"][name] for name in defaults} == both_null
        return run


async def exercise_atomic_unlimited_reservations(storage):
    run = await storage.create_run(
        RunCreate(
            user_request="Count every call",
            limits=RunLimits(max_model_calls=None, worker_model_calls=None, max_tool_calls=2),
        ).model_dump(mode="json")
    )
    reservations = await asyncio.gather(
        *(storage.reserve_budget(run["run_id"], "model") for _ in range(125))
    )
    assert sorted(reservations) == list(range(1, 126))
    assert await storage.reserve_budget(run["run_id"], "model", amount=5) == 130
    current = await storage.get_run(run["run_id"])
    assert current["model_calls"] == 130 and current["limits"]["max_model_calls"] is None
    tool_results = await asyncio.gather(
        *(storage.reserve_budget(run["run_id"], "tool") for _ in range(4)), return_exceptions=True
    )
    assert sorted(value for value in tool_results if isinstance(value, int)) == [1, 2]
    assert sum(isinstance(value, BudgetExceeded) for value in tool_results) == 2
    assert (await storage.get_run(run["run_id"]))["tool_calls"] == 2
    finite = await storage.create_run(
        RunCreate(
            user_request="Global finite remains enforced",
            limits=RunLimits(max_model_calls=2, worker_model_calls=None),
        ).model_dump(mode="json")
    )
    assert await storage.reserve_budget(finite["run_id"], "model", amount=2) == 2
    with pytest.raises(BudgetExceeded):
        await storage.reserve_budget(finite["run_id"], "model")
    return run


async def test_memory_unlimited_defaults_overrides_idempotency_and_atomic_usage(tmp_path):
    storage = MemoryStorage()
    await exercise_nullable_api(storage, tmp_path)
    await exercise_atomic_unlimited_reservations(storage)


@pytest.mark.integration
async def test_postgres_unlimited_budgets_survive_reopen_with_atomic_usage(tmp_path, postgres_url):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        snapshot = await exercise_nullable_api(storage, tmp_path)
        counted = await exercise_atomic_unlimited_reservations(storage)
    finally:
        await storage.close()
    reopened = PostgresStorage(postgres_url)
    await reopened.open()
    try:
        assert await reopened.get_setting("model_call_budget") == {
            "max_model_calls": None,
            "worker_model_calls": None,
            "max_tool_calls": 200,
        }
        assert (await reopened.get_run(snapshot["run_id"]))["limits"] == snapshot["limits"]
        assert (await reopened.get_run(counted["run_id"]))["model_calls"] == 130
        assert await reopened.reserve_budget(counted["run_id"], "model") == 131
    finally:
        await reopened.close()
