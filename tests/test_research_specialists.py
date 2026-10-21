"""Research leads create named workers using real inherited-role tool loops."""

import json

import pytest
from test_agent_services import assignment, services_with_provider, tool_call

from org_harness.models import (
    SPECIALIST_CORE_TOOL_NAMES,
    Constitution,
    Deliverable,
    EscalationSignal,
    TacticalPlan,
    TaskSpecialistSpec,
    worker_agent_id,
    worker_agent_metadata,
    worker_tool_names,
)


@pytest.mark.parametrize("role", ["market_researcher", "data_analyst"])
@pytest.mark.parametrize("narrowed", [False, True])
async def test_research_lead_creates_named_worker_with_real_search_and_output_evidence(
    tmp_path, monkeypatch, role, narrowed
):
    kr, work = assignment()
    kr = kr.model_copy(
        update={
            "target_department": "research",
            "description": "Explain the paper using source evidence",
            "acceptance_criteria": ("A report links its conclusions to the paper",),
        }
    )
    selected = ("search_market_data",) + (("run_command",) if role == "data_analyst" else ())
    work = work.model_copy(
        update={
            "role": role,
            "task": kr.description,
            "acceptance_criteria": kr.acceptance_criteria,
            "specialist": TaskSpecialistSpec(
                name="bioRxiv Content Cartographer",
                instructions="Map the paper's supported claims, preserving its canonical URL.",
                tools=selected if narrowed else (),
            ),
        }
    )
    searches = []
    model_roles = []

    def script(body, requests):
        if len(requests) == 1:
            assert body["response_format"] == {"type": "json_object"}
            assert "tools" not in body
            assert "task-specific" in body["messages"][0]["content"]
            assert "market_researcher" in body["messages"][0]["content"]
            return {"content": TacticalPlan(work_packages=(work,)).model_dump_json()}
        if body.get("response_format"):
            payload = json.loads(body["messages"][-1]["content"])
            return {
                "content": Deliverable(
                    kr_id=payload["kr_id"],
                    department=payload["department"],
                    worker_role=payload["worker_role"],
                    summary="Mapped the paper's claims to its source and saved the report.",
                ).model_dump_json()
            }
        names = {item["function"]["name"] for item in body["tools"]}
        assert names == (
            set(selected) | SPECIALIST_CORE_TOOL_NAMES if narrowed else worker_tool_names(role)
        )
        assert not names & {"consult_tools_rd", "register_mission_tool"}
        assert ("run_mission_tool" in names) == (role == "data_analyst" and not narrowed)
        assert ("run_command" in names) == (role == "data_analyst")
        assert work.specialist.instructions in body["messages"][0]["content"]
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if not results:
            return {
                "tool_calls": [
                    tool_call("search_market_data", {"query": "canonical paper claims"}, "search")
                ]
            }
        if len(results) == 1:
            calls = [
                tool_call(
                    "write_file",
                    {
                        "path": "report.md",
                        "content": "# Evidence map\nThe supported claim is documented at https://paper.invalid/canonical.\n",
                    },
                    "write-report",
                )
            ]
            if role == "data_analyst":
                calls.append(
                    tool_call("run_command", {"command": "python3 -c 'print(1+1)'"}, "verify")
                )
            return {"tool_calls": calls}
        return {"content": "Saved report.md with the canonical source and verified evidence."}

    async with services_with_provider(tmp_path, script) as (
        services,
        storage,
        run,
        requests,
        workspace,
    ):

        async def search(query, call_id):
            searches.append((query, call_id))
            return {
                "results": [{"url": "https://paper.invalid/canonical", "text": "Supported claim"}]
            }

        monkeypatch.setattr(services, "_search_web", search)
        original_model_for = services.model_for

        def model_for(role=None):
            model_roles.append(role)
            return original_model_for(role)

        monkeypatch.setattr(services, "model_for", model_for)
        packages = await services.plan_work(kr, Constitution(), [], "")
        assert packages == [work]
        assert len(requests) == 1
        result = await services.execute(packages[0], kr, Constitution(), [], "", 0)
        actor = worker_agent_id(run["run_id"], work)
        assert result.worker_role == actor
        assert result.department == "research" and not result.fallback
        assert len(requests) == 5
        assert model_roles == ["research_head", role, role]
        assert searches == [("canonical paper claims", "search")]
        assert "https://paper.invalid/canonical" in (workspace / "report.md").read_text()
        artifacts = [await storage.get_artifact(item) for item in result.artifact_ids]
        assert {item["kind"] for item in artifacts} >= {"agent_assignment", "research", "source"}
        proof = next(item for item in artifacts if item["kind"] == "agent_assignment")
        _, content = await services.artifacts.read(proof["artifact_id"], limit=None)
        assignment_proof = json.loads(content)
        assert assignment_proof["agent_id"] == actor
        assert assignment_proof["agent_type"] == "research_specialist"
        assert assignment_proof["parent_agent_id"] == "research_head"
        assert (
            assignment_proof["work"]["specialist"]["instructions"] == work.specialist.instructions
        )
        events = [item for item in storage.events if item["agent_id"] == actor]
        assert {item["activity"] for item in events} >= {"executing", "reading", "writing"}
        assert all(item["kr_id"] == kr.kr_id for item in events)
        metadata = worker_agent_metadata(work)
        assert all(
            all(item["data"][key] == value for key, value in metadata.items()) for item in events
        )
        assert not any(item["agent_id"] == "tools_rd_lead" for item in storage.events)


@pytest.mark.parametrize("forged_department", [False, True])
async def test_direct_worker_execution_rejects_forged_role_capabilities_before_any_effect(
    tmp_path, forged_department
):
    kr, work = assignment()
    work = work.model_copy(
        update={
            "role": "market_researcher",
            "specialist": TaskSpecialistSpec(
                name="Paper analyst",
                instructions="Analyze evidence.",
                tools=() if forged_department else ("run_command",),
            ),
        }
    )
    if not forged_department:
        kr = kr.model_copy(update={"target_department": "research"})
    async with services_with_provider(tmp_path, lambda *_: {}) as (
        services,
        storage,
        run,
        requests,
        _,
    ):
        with pytest.raises(EscalationSignal) as error:
            await services.execute(work, kr, Constitution(), [], "", 0)
        assert error.value.kind == "invalid_plan"
        assert not requests and not storage.events and not storage.operations
        assert not await storage.list_artifacts(run["run_id"])
