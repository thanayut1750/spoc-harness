"""Planning journals replay unchanged context without aliasing new authorized attempts."""

import json

import pytest
from test_agent_services import assignment, services_with_provider, tool_call

from org_harness.models import Constitution, Deliverable, TacticalPlan


@pytest.mark.parametrize(
    "changed_feedback",
    [
        "Gate rejected the output: complete the missing interaction.",
        "Human context for the next epoch: use an offline Three.js copy.",
    ],
)
async def test_new_planning_context_reuses_call_id_without_replaying_prior_rd(
    tmp_path, monkeypatch, changed_feedback
):
    kr, work = assignment()
    consultations = []

    def provider(body, requests):
        if not any(message["role"] == "tool" for message in body["messages"]):
            return {
                "tool_calls": [
                    tool_call(
                        "consult_tools_rd",
                        {"requirement": "Research a lightweight 3D capability", "mode": "research"},
                        "provider-reused-call-id",
                    )
                ]
            }
        return {"content": TacticalPlan(work_packages=(work,)).model_dump_json()}

    async with services_with_provider(tmp_path, provider) as (services, storage, run, requests, _):

        async def rd_worker(work, kr, constitution, inputs, feedback, epoch, host, **kwargs):
            consultations.append(host.workspace)
            source = await host.write_file(
                "research-evidence", "research.md", "A recorded, substantive technical finding."
            )
            return Deliverable(
                kr_id=kr.kr_id,
                department="engineering",
                worker_role=host.role,
                summary="Researched the capability and recorded the findings.",
                artifact_ids=(source["artifact_id"],),
            )

        monkeypatch.setattr(services, "_execute_worker", rd_worker)
        original = await services.plan_work(kr, Constitution(), [], "")
        assert len(consultations) == 1
        # A root checkpoint replay can rerun the planning node. Identical model
        # calls still reuse the completed consultation rather than repeat it.
        assert await services.plan_work(kr, Constitution(), [], "") == original
        assert len(consultations) == 1
        revised = await services.plan_work(kr, Constitution(), [], changed_feedback)
        assert revised == original
        assert len(consultations) == 2
        assert consultations[0] != consultations[1]
        assert await services.plan_work(kr, Constitution(), [], changed_feedback) == revised
        assert len(consultations) == 2
        records = [
            item
            for item in await storage.list_artifacts(run["run_id"])
            if item["name"].startswith("tools_rd_consultation-")
        ]
        assert len(records) == 2
        scopes = [json.loads(item["scope"]) for item in records]
        assert all(scope[-1] == "engineering_head" for scope in scopes)
        assert scopes[0] != scopes[1]
        assert all(item["status"] == "done" for item in storage.operations.values())
        assert not await storage.uncertain_operations(run["run_id"])
        assert len(requests) == 8  # Two planning turns per invocation, no real R&D model.


async def test_planning_scope_is_canonical_and_separates_dependency_inputs(tmp_path):
    kr, _ = assignment()
    async with services_with_provider(tmp_path, lambda *_: {}) as (services, _, _, requests, _):
        first = services._planning_host(
            "engineering_head", kr, payload={"feedback": "same", "inputs": [{"summary": "first"}]}
        )
        reordered = services._planning_host(
            "engineering_head", kr, payload={"inputs": [{"summary": "first"}], "feedback": "same"}
        )
        changed = services._planning_host(
            "engineering_head", kr, payload={"feedback": "same", "inputs": [{"summary": "new"}]}
        )
        assert first.operation_id("call", "run_mission_tool") == reordered.operation_id(
            "call", "run_mission_tool"
        )
        assert first.operation_id("call", "run_mission_tool") != changed.operation_id(
            "call", "run_mission_tool"
        )
        assert json.loads(first.scope)[-1] == "engineering_head"
        assert not requests
