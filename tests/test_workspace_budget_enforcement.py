"""Saved workspace budgets reach the real agent loop without changing existing missions."""

import json

import httpx
import pytest
from test_agent_services import assignment, services_with_provider, tool_call

from org_harness.agent_services import AgentServices
from org_harness.api import create_app
from org_harness.models import Constitution, Deliverable, EscalationSignal


@pytest.mark.parametrize("mission_budget", [18, 17])
async def test_workspace_budget_controls_real_seventeen_turn_worker_and_global_extraction_cap(
    tmp_path, mission_budget
):
    key_result, work = assignment()

    def script(body, requests):
        if body.get("response_format"):
            context = json.loads(body["messages"][-1]["content"])
            return {
                "content": Deliverable(
                    kr_id=context["kr_id"],
                    department=context["department"],
                    worker_role=context["worker_role"],
                    summary="Completed the saved output after seventeen agent turns.",
                ).model_dump_json()
            }
        turn = len(requests)
        if turn == 17:
            return {"content": "Completed output.txt using the recorded tool evidence."}
        return {
            "tool_calls": [
                tool_call(
                    "write_file" if turn == 1 else "read_file",
                    {
                        "path": "output.txt",
                        **({"content": "Preserved verified output"} if turn == 1 else {}),
                    },
                    f"step-{turn}",
                )
            ]
        }

    async with services_with_provider(tmp_path, script) as (
        provider_fixture,
        storage,
        _,
        requests,
        workspace,
    ):
        settings = provider_fixture.settings
        app = create_app(settings, storage)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            prior = await client.post("/api/runs", json={"user_request": "Existing mission"})
            assert prior.status_code == 202
            prior_id = prior.json()["run_id"]
            prior_snapshot = await storage.get_run(prior_id)

            saved_budget = {"max_model_calls": mission_budget, "worker_model_calls": 17}
            saved = await client.put("/api/settings/budgets", json=saved_budget)
            assert saved.status_code == 200
            assert saved.json()["model_call_budget"] == saved_budget
            assert (await client.get("/api/settings")).json()["model_call_budget"] == saved_budget
            response = await client.post(
                "/api/runs",
                json={
                    "user_request": "Produce a verified output",
                    "workspace_path": str(workspace),
                },
            )
            assert response.status_code == 202
            run_id = response.json()["run_id"]
            run = await storage.get_run(run_id)
            assert {name: run["limits"][name] for name in saved_budget} == saved_budget
            assert await storage.get_run(prior_id) == prior_snapshot

            # Later preference changes apply only to future missions. Execute
            # this saved mission with a fresh AgentServices instance afterwards.
            changed = await client.put(
                "/api/settings/budgets", json={"max_model_calls": 30, "worker_model_calls": 2}
            )
            assert changed.status_code == 200
            assert (await storage.get_run(run_id))["limits"] == run["limits"]

        services = AgentServices(settings, storage, await storage.get_run(run_id))
        configured_model = services.model
        services.model = provider_fixture.model
        try:
            assert services.limits.worker_model_calls == 17
            assert services.limits.max_model_calls == mission_budget
            if mission_budget == 18:
                result = await services.execute(work, key_result, Constitution(), [], "", 0)
                assert not result.fallback and result.artifact_ids
            else:
                with pytest.raises(EscalationSignal) as error:
                    await services.execute(work, key_result, Constitution(), [], "", 0)
                assert error.value.kind == "limit_exceeded"
        finally:
            # The shared mocked provider belongs to the outer fixture. Close
            # this instance's separately created, unused configured model here.
            services.model = configured_model
            await services.close()

        persisted = await storage.get_run(run_id)
        assert persisted["model_calls"] == len(requests) == mission_budget
        assert persisted["tool_calls"] == 16
        assert sum(not item.get("response_format") for item in requests) == 17
        assert sum(bool(item.get("response_format")) for item in requests) == (mission_budget == 18)
        assert (workspace / "output.txt").read_text() == "Preserved verified output"
        artifacts = await storage.list_artifacts(run_id)
        assert any(item["kind"] == "source" for item in artifacts)
        assert any(item["kind"] == "deliverable" for item in artifacts) == (mission_budget == 18)
        assert await storage.get_run(prior_id) == prior_snapshot
