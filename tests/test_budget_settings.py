"""Workspace model budgets become immutable run snapshots without rewriting prior intent."""

import asyncio

import httpx
import pytest

from org_harness.agent_services import AgentServices
from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.models import ModelCallBudget, ModelCallBudgetUpdate, RunCreate, RunLimits
from org_harness.storage import BudgetExceeded, ConflictError, MemoryStorage, PostgresStorage


async def exercise_budget_settings(storage, tmp_path):
    settings = Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path)
    app = create_app(settings, storage)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        initial = (await client.get("/api/settings")).json()
        assert initial["model_call_budget"] == {"max_model_calls": 100, "worker_model_calls": 12}
        assert await storage.get_setting("model_call_budget") is None
        for invalid in (
            {},
            {"max_model_calls": 5},
            {"max_model_calls": 0, "worker_model_calls": 2},
            {"max_model_calls": 10001, "worker_model_calls": 2},
            {"max_model_calls": 10, "worker_model_calls": 0},
            {"max_model_calls": 10, "worker_model_calls": 101},
            {"max_model_calls": 1.5, "worker_model_calls": 2},
            {"max_model_calls": 10, "worker_model_calls": 2, "max_tool_calls": 4},
        ):
            assert (await client.put("/api/settings/budgets", json=invalid)).status_code == 422
        assert (await client.get("/api/settings")).json() == initial
        assert await storage.get_setting("model_call_budget") is None
        old_payload = RunCreate(user_request="Legacy request").model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        legacy = await storage.create_run(
            {
                **old_payload,
                "model_config": settings.default_model_selection().model_dump(mode="json"),
                "agent_model_configs": {},
            },
            "legacy-idempotency",
            request_payload=old_payload,
        )
        saved = await client.put(
            "/api/settings/budgets", json={"max_model_calls": 10, "worker_model_calls": 2}
        )
        assert saved.status_code == 200
        assert saved.json() == {
            **initial,
            "model_call_budget": {"max_model_calls": 10, "worker_model_calls": 2},
        }
        snapshots = []
        for request, expected in (
            ({"user_request": "Omitted limits"}, (10, 2)),
            ({"user_request": "Empty limits", "limits": {}}, (10, 2)),
            ({"user_request": "Explicit global", "limits": {"max_model_calls": 7}}, (7, 2)),
            ({"user_request": "Explicit worker", "limits": {"worker_model_calls": 3}}, (10, 3)),
            (
                {
                    "user_request": "Explicit defaults",
                    "limits": {
                        "max_model_calls": 100,
                        "worker_model_calls": 12,
                        "worker_timeout": 60,
                        "max_tool_calls": 41,
                    },
                },
                (100, 12),
            ),
        ):
            response = await client.post("/api/runs", json=request)
            assert response.status_code == 202
            run = await storage.get_run(response.json()["run_id"])
            assert (
                run["limits"]["max_model_calls"],
                run["limits"]["worker_model_calls"],
            ) == expected
            assert run["limits"]["worker_timeout"] == request.get("limits", {}).get(
                "worker_timeout", 3600
            )
            if request["user_request"] == "Explicit defaults":
                assert run["limits"]["max_tool_calls"] == 41
            snapshots.append(run)
        services = AgentServices(settings, storage, snapshots[0])
        try:
            assert services.limits.max_model_calls == 10 and services.limits.worker_model_calls == 2
        finally:
            await services.close()
        for _ in range(10):
            await storage.reserve_budget(snapshots[0]["run_id"], "model")
        with pytest.raises(BudgetExceeded):
            await storage.reserve_budget(snapshots[0]["run_id"], "model")

        headers = {"Idempotency-Key": "new-budget-snapshot"}
        request = {"user_request": "Versioned request"}
        created = await client.post("/api/runs", json=request, headers=headers)
        original = await storage.get_run(created.json()["run_id"])
        await client.put(
            "/api/settings/budgets", json={"max_model_calls": 20, "worker_model_calls": 4}
        )
        assert (
            await client.post("/api/runs", json=request, headers=headers)
        ).json() == created.json()
        assert (await storage.get_run(original["run_id"]))["limits"] == original["limits"]
        # A new versioned key distinguishes an omitted field from an explicit
        # schema default, even though their normalized legacy bodies are equal.
        for limits in ({"max_model_calls": 100}, {"worker_model_calls": 12}):
            assert (
                await client.post("/api/runs", json={**request, "limits": limits}, headers=headers)
            ).status_code == 409
        replayed_legacy = await client.post(
            "/api/runs",
            json={"user_request": "Legacy request"},
            headers={"Idempotency-Key": "legacy-idempotency"},
        )
        assert replayed_legacy.json()["run_id"] == legacy["run_id"]
        assert (await storage.get_run(legacy["run_id"]))["limits"]["max_model_calls"] == 100
        assert (
            await client.post(
                "/api/runs",
                json={"user_request": "Changed legacy request"},
                headers={"Idempotency-Key": "legacy-idempotency"},
            )
        ).status_code == 409
        for before in snapshots[1:]:
            assert (await storage.get_run(before["run_id"]))["limits"] == before["limits"]
        reset = await client.post("/api/regenesis", json={"confirmation": "REGENESIS"})
        assert reset.status_code == 200
        assert reset.json()["settings"]["model_call_budget"] == initial["model_call_budget"]
        assert await storage.get_setting("model_call_budget") is None
        after = await client.post("/api/runs", json={"user_request": "After reset"})
        after_run = await storage.get_run(after.json()["run_id"])
        assert after_run["limits"]["max_model_calls"] == 100
        assert after_run["limits"]["worker_model_calls"] == 12
        assert after_run["limits"]["worker_timeout"] == 3600
        saved = await client.put(
            "/api/settings/budgets", json={"max_model_calls": 10000, "worker_model_calls": 100}
        )
        assert saved.status_code == 200
        return saved.json()["model_call_budget"]


async def exercise_create_race(storage):
    payload = RunCreate(user_request="Concurrent versioned request").model_dump(mode="json")
    request = {"fingerprint_version": 2, "request": payload, "explicit_budget_fields": []}
    values = await asyncio.gather(
        *(
            storage.create_run(
                payload, "concurrent", request_payload=request, legacy_request_payload=payload
            )
            for _ in range(6)
        )
    )
    assert len({value["run_id"] for value in values}) == 1
    with pytest.raises(ConflictError):
        await storage.create_run(
            payload,
            "concurrent",
            request_payload={**request, "explicit_budget_fields": ["max_model_calls"]},
            legacy_request_payload=payload,
        )
    legacy_payload = RunCreate(user_request="Concurrent legacy request").model_dump(mode="json")
    legacy = await storage.create_run(legacy_payload, "concurrent-legacy")
    replays = await asyncio.gather(
        *(
            storage.create_run(
                legacy_payload,
                "concurrent-legacy",
                request_payload={"fingerprint_version": 2, "request": legacy_payload},
                legacy_request_payload=legacy_payload,
            )
            for _ in range(6)
        )
    )
    assert all(replay["run_id"] == legacy["run_id"] for replay in replays)


def test_shared_model_budget_defaults_and_bounds_match_run_limits():
    for name in ModelCallBudget.model_fields:
        budget = ModelCallBudget.model_json_schema()["properties"][name]
        limits = RunLimits.model_json_schema()["properties"][name]
        update = ModelCallBudgetUpdate.model_json_schema()["properties"][name]
        assert budget == limits
        assert update["anyOf"] == budget["anyOf"]
    assert ModelCallBudgetUpdate.model_json_schema()["required"] == [
        "max_model_calls",
        "worker_model_calls",
    ]


async def test_memory_workspace_budgets_and_versioned_create_idempotency(tmp_path):
    storage = MemoryStorage()
    await exercise_budget_settings(storage, tmp_path)
    await exercise_create_race(storage)


@pytest.mark.integration
async def test_postgres_workspace_budgets_persist_and_create_idempotency_remains_atomic(
    tmp_path, postgres_url
):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        saved = await exercise_budget_settings(storage, tmp_path)
        await exercise_create_race(storage)
    finally:
        await storage.close()
    restored = PostgresStorage(postgres_url)
    await restored.open()
    try:
        settings = Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(settings, restored)),
            base_url="http://test",
        ) as client:
            assert (await client.get("/api/settings")).json()["model_call_budget"] == saved
    finally:
        await restored.close()
