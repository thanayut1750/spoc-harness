"""Exercise task-specific agents and on-demand Tools R&D through real LangChain loops."""

import asyncio
import json
from pathlib import Path

import pytest
from test_agent_services import approve, assignment, services_with_provider, tool_call

from org_harness import agent_services
from org_harness.agent_services import ToolsResearchResult, WorkerHostTools
from org_harness.models import (
    ENGINEERING_CORE_TOOL_NAMES,
    Constitution,
    Deliverable,
    EngineeringSpecialistSpec,
    EscalationSignal,
    StrategicObjective,
    StrategicPlan,
    TacticalPlan,
    worker_agent_id,
)
from org_harness.runtime import gate_approved

PLANNING_TOOL_NAMES = {
    "consult_tools_rd",
    "run_mission_tool",
    "start_async_task",
    "check_async_task",
    "list_async_tasks",
    "cancel_async_task",
    "wait_async_task",
}


def extracted_deliverable(body):
    payload = json.loads(body["messages"][-1]["content"])
    return {
        "content": Deliverable(
            kr_id=payload["kr_id"],
            department=payload["department"],
            worker_role=payload["worker_role"],
            summary="Completed the assigned output using recorded tool evidence.",
        ).model_dump_json()
    }


def expire_parent_deadline_after(monkeypatch, started):
    """Expire the actual outer wait only after its nested work reached the test gate.

    Agent/model setup can take arbitrarily long under concurrent test load. Keep
    the real planning and cancellation stack, but control the timer's firing
    point instead of depending on setup fitting inside a few milliseconds.
    Nested R&D deadlines stay inactive here to isolate the parent deadline.
    """
    deadlines = []

    class ControlledDeadline:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        async def wait_for(self, awaitable, timeout):
            deadlines.append(timeout)
            if len(deadlines) != 1:
                return await awaitable
            task = asyncio.create_task(awaitable)
            try:
                await asyncio.wait_for(started(), timeout=5)
                return await asyncio.wait_for(task, timeout=0)
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    # Patching this module reference leaves the real asyncio timers used by
    # HostTools, subprocess cleanup, provider transports, and this gate intact.
    monkeypatch.setattr(agent_services, "asyncio", ControlledDeadline())
    return deadlines


async def test_engineering_lead_creates_real_task_specific_worker_in_one_planning_call(tmp_path):
    kr, work = assignment()
    spec = EngineeringSpecialistSpec(
        name="Three.js lighting engineer",
        instructions="Implement cinematic Three.js lighting, then verify scene initialization.",
        tools=("write_file",),
    )
    work = work.model_copy(update={"specialist": spec})
    model_roles = []

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        prompt = body["messages"][0]["content"]
        names = {item["function"]["name"] for item in body["tools"]}
        if len(requests) == 1:
            assert names == PLANNING_TOOL_NAMES
            assert "task-specific" in prompt
            return {"content": TacticalPlan(work_packages=(work,)).model_dump_json()}
        assert spec.instructions in prompt
        assert "cinematic" in prompt and kr.description in prompt
        assert names == ENGINEERING_CORE_TOOL_NAMES
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if not results:
            return {
                "tool_calls": [
                    tool_call(
                        "write_file", {"path": "scene.js", "content": "const lighting = true;"}
                    )
                ]
            }
        return {"content": "Created the scene lighting output."}

    async with services_with_provider(tmp_path, script) as (
        services,
        storage,
        run,
        requests,
        workspace,
    ):
        model_for = services.model_for

        def recorded_model_role(role=None):
            model_roles.append(role)
            return model_for(role)

        services.model_for = recorded_model_role
        packages = await services.plan_work(kr, Constitution(), [], "")
        assert len(requests) == 1 and packages[0].specialist == spec
        result = await services.execute(packages[0], kr, Constitution(), [], "", 0)
        identity = worker_agent_id(run["run_id"], work)
        assert result.worker_role == identity
        assert len(requests) == 4  # One tactical call, two worker calls, one extraction.
        assert model_roles == ["engineering_head", work.role, work.role]
        assert (workspace / "scene.js").read_text() == "const lighting = true;"
        events = [item for item in storage.events if item["agent_id"] == identity]
        assert len(events) >= 2
        assert all(item["data"]["display_name"] == spec.name for item in events)
        assert all(item["data"]["parent_agent_id"] == "engineering_head" for item in events)
        assert all(item["data"]["agent_type"] == "engineering_specialist" for item in events)
        assert all(item["data"]["model_parent"] == work.role for item in events)
        assert not await services.mission_tools().list_tools()


async def test_planner_with_optional_rd_tools_still_uses_one_call_for_ordinary_plan(tmp_path):
    kr, _ = assignment()
    plan = StrategicPlan(
        objectives=(
            StrategicObjective(objective_id="objective", title="Website", key_results=(kr,)),
        )
    )

    def script(body, requests):
        assert not body.get("response_format")
        assert {item["function"]["name"] for item in body["tools"]} == PLANNING_TOOL_NAMES
        return {"content": plan.model_dump_json()}

    async with services_with_provider(tmp_path, script) as (services, storage, run, requests, _):
        objectives = await services.plan("Build a website", Constitution())
        assert objectives == list(plan.objectives)
        assert len(requests) == 1
        assert not storage.operations
        assert not await storage.list_artifacts(run["run_id"])


async def test_research_lead_keeps_its_direct_structured_call_without_rd_capability(tmp_path):
    kr, work = assignment()
    kr = kr.model_copy(update={"target_department": "research"})
    work = work.model_copy(update={"role": "market_researcher"})

    def script(body, requests):
        assert body["response_format"] == {"type": "json_object"}
        assert "tools" not in body
        return {"content": TacticalPlan(work_packages=(work,)).model_dump_json()}

    async with services_with_provider(tmp_path, script) as (services, _, _, requests, _):
        packages = await services.plan_work(kr, Constitution(), [], "")
        assert len(packages) == 1
        assert packages[0].model_copy(update={"specialist": None}) == work
        assert packages[0].specialist.name == work.task
        assert work.task in packages[0].specialist.instructions
        assert kr.acceptance_criteria[0] in packages[0].specialist.instructions
        assert len(requests) == 1


@pytest.mark.parametrize("caller", ["backend_coder", "research_head", "executive", "tools_rd_lead"])
async def test_rd_capability_is_rejected_server_side_for_other_callers(tmp_path, caller):
    kr, _ = assignment()
    async with services_with_provider(tmp_path, lambda *_: {}) as (services, _, _, requests, _):
        host = services._planning_host(caller, kr)
        with pytest.raises(EscalationSignal) as error:
            await services.consult_tools_rd(
                caller, "Build an importer", Constitution(), host, "rd", kr
            )
        assert error.value.kind == "policy_violation"
        assert not requests


async def test_planning_limits_parallel_rd_consultations_to_two(tmp_path, monkeypatch):
    kr, work = assignment()
    calls = []

    def script(body, requests):
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if not results:
            return {
                "tool_calls": [
                    tool_call("consult_tools_rd", {"requirement": f"Capability {i}"}, f"rd-{i}")
                    for i in range(3)
                ]
            }
        assert len(results) == 3
        assert sum("consultation limit" in item["content"] for item in results) == 1
        return {"content": TacticalPlan(work_packages=(work,)).model_dump_json()}

    async with services_with_provider(tmp_path, script) as (services, _, _, requests, _):

        async def consult(caller, requirement, *args, **kwargs):
            calls.append((caller, requirement))
            return {"report": "Existing capability identified", "artifact_ids": []}

        monkeypatch.setattr(services, "consult_tools_rd", consult)
        await services.plan_work(kr, Constitution(), [], "")
        assert len(calls) == 2 and len(requests) == 2


async def test_planning_deadline_cancels_nested_rd_work(tmp_path, monkeypatch):
    kr, _ = assignment()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    def script(body, requests):
        return {"tool_calls": [tool_call("consult_tools_rd", {"requirement": "Slow capability"})]}

    async with services_with_provider(tmp_path, script, limits={"worker_timeout": 0.2}) as (
        services,
        _,
        _,
        requests,
        _,
    ):

        async def blocked(*args, **kwargs):
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(services, "consult_tools_rd", blocked)
        deadlines = expire_parent_deadline_after(monkeypatch, started.wait)
        with pytest.raises(EscalationSignal) as error:
            await services.plan_work(kr, Constitution(), [], "")
        assert error.value.kind == "worker_timeout"
        assert cancelled.is_set()
        assert len(requests) == 1
        assert deadlines == [0.2]


async def test_research_only_rd_returns_recorded_report_without_registration(tmp_path, monkeypatch):
    kr, work = assignment()

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        prompt = body["messages"][0]["content"]
        names = {item["function"]["name"] for item in body["tools"]}
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if prompt.startswith("You are tools_rd_lead"):
            assert "register_mission_tool" not in names
            assert "consult_tools_rd" not in names
            if not results:
                assert "Requested mode: research" in body["messages"][-1]["content"]
                return {
                    "tool_calls": [
                        tool_call(
                            "search_market_data", {"query": "Three.js lighting options"}, "source"
                        )
                    ]
                }
            return {
                "content": "Use ambient light plus one directional light; no custom tool is needed."
            }
        if not results:
            return {
                "tool_calls": [
                    tool_call(
                        "consult_tools_rd",
                        {
                            "requirement": "Research suitable lighting techniques",
                            "mode": "research",
                        },
                        "research-only",
                    )
                ]
            }
        report = json.loads(results[0]["content"])["result"]
        assert report["mode"] == "research" and report["tools"] == []
        assert report["report_artifact_id"] in report["artifact_ids"]
        return {"content": TacticalPlan(work_packages=(work,)).model_dump_json()}

    async with services_with_provider(tmp_path, script) as (services, storage, run, requests, _):

        async def research(*args):
            return {"url": "https://threejs.org/docs/", "finding": "Documented light sources"}

        monkeypatch.setattr(services, "_invoke_mcp", research)
        await services.plan_work(kr, Constitution(), [], "")
        assert len(requests) == 5  # Lead 2, R&D 2, typed R&D extraction 1.
        artifacts = await storage.list_artifacts(run["run_id"])
        reports = [
            item for item in artifacts if item["kind"] == "source" and item["name"] == "report.md"
        ]
        assert len(reports) == 1
        _, content = await services.artifacts.read(reports[0]["artifact_id"], limit=None)
        assert content.strip() and "Recorded evidence" in content
        assert not await services.mission_tools().list_tools()


async def test_consultation_replay_reuses_evidence_and_rejects_changed_mode(tmp_path, monkeypatch):
    kr, work = assignment()
    requested_mode = "research"
    delegations = []

    def script(body, requests):
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if not results:
            return {
                "tool_calls": [
                    tool_call(
                        "consult_tools_rd",
                        {"requirement": "Investigate the same capability", "mode": requested_mode},
                        "same-consultation",
                    )
                ]
            }
        return {"content": TacticalPlan(work_packages=(work,)).model_dump_json()}

    async with services_with_provider(tmp_path, script) as (services, storage, _, requests, _):

        async def consult(*args, **kwargs):
            delegations.append(kwargs["mode"])
            return {"report": "Reviewed available techniques", "artifact_ids": []}

        monkeypatch.setattr(services, "consult_tools_rd", consult)
        await services.plan_work(kr, Constitution(), [], "")
        await services.plan_work(kr, Constitution(), [], "")
        assert delegations == ["research"]
        assert sum(item["kind"] == "tool" for item in storage.operations.values()) == 1
        assert sum(item["kind"] == "rd_delegation" for item in storage.operations.values()) == 1
        requested_mode = "build_tool"
        with pytest.raises(EscalationSignal) as error:
            await services.plan_work(kr, Constitution(), [], "")
        assert error.value.kind == "operation_conflict"
        assert delegations == ["research"] and len(requests) == 5


async def test_build_mode_cannot_claim_success_without_tested_registration(tmp_path, monkeypatch):
    kr, _ = assignment()

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if not results:
            return {
                "tool_calls": [
                    tool_call("search_market_data", {"query": "An unbuilt capability"}, "reference")
                ]
            }
        return {"content": "Claims a tool was built but supplies only source research."}

    async with services_with_provider(tmp_path, script) as (services, _, _, requests, _):

        async def research(*args):
            return {"finding": "Research is available, but no tested tool exists"}

        monkeypatch.setattr(services, "_invoke_mcp", research)
        host = services._planning_host("engineering_head", kr)
        with pytest.raises(EscalationSignal) as error:
            await services.consult_tools_rd(
                "engineering_head",
                "Build a tool",
                Constitution(),
                host,
                "build",
                kr,
                mode="build_tool",
            )
        assert error.value.kind == "missing_deliverable"
        assert len(requests) == 3
        assert not await services.mission_tools().list_tools()


async def test_parent_deadline_preserves_nested_rd_command_side_effect_review(
    tmp_path, monkeypatch
):
    kr, _ = assignment()

    def script(body, requests):
        prompt = body["messages"][0]["content"]
        if prompt.startswith("You are tools_rd_lead"):
            return {
                "tool_calls": [
                    tool_call(
                        "run_command",
                        {"command": "printf started > nested.txt; sleep 30"},
                        "long-command",
                    )
                ]
            }
        return {
            "tool_calls": [
                tool_call("consult_tools_rd", {"requirement": "Investigate a slow command"}, "rd")
            ]
        }

    async with services_with_provider(tmp_path, script, limits={"worker_timeout": 0.15}) as (
        services,
        storage,
        run,
        requests,
        _,
    ):
        marker_paths = []

        async def command_started():
            private_root = services.settings.data_dir / "workspaces" / run["run_id"] / "tools-rd"
            while True:
                markers = list(private_root.rglob("nested.txt"))
                if markers and markers[0].read_text() == "started":
                    break
                await asyncio.sleep(0.01)
            marker_paths.extend(markers)
            assert len(markers) == 1 and markers[0].read_text() == "started"

        deadlines = expire_parent_deadline_after(monkeypatch, command_started)
        with pytest.raises(EscalationSignal) as error:
            await services.plan_work(kr, Constitution(), [], "")
        assert error.value.kind == "unknown_operation"
        assert len(requests) == 2
        assert deadlines == [0.15, 0.15]
        assert marker_paths[0].read_text() == "started"
        pending = await storage.uncertain_operations(run["run_id"])
        assert len(pending) == 1 and pending[0]["status"] == "pending"


async def test_parallel_rd_consultations_use_private_workspaces_and_preserve_user_project(
    tmp_path, monkeypatch
):
    kr, _ = assignment()
    workspaces = []
    sources_written = asyncio.Event()

    async with services_with_provider(
        tmp_path, lambda *_: {}, limits={"worker_model_calls": 12}
    ) as (
        services,
        _,
        run,
        requests,
        external_workspace,
    ):
        original = "# Existing user tool; leave these exact bytes in place.\n"
        (external_workspace / "tool.py").write_text(original)
        parent = services._planning_host("engineering_head", kr)

        async def build(work, research_kr, constitution, inputs, feedback, epoch, host, **kwargs):
            position = len(workspaces)
            workspaces.append(host.workspace)
            source = f"import json,sys\njson.load(sys.stdin)\nprint(json.dumps({{'owner': {position}}}))\n"
            saved = await host.write_file("source", "tool.py", source)
            assert not saved.get("error")
            if len(workspaces) == 2:
                sources_written.set()
            await sources_written.wait()
            registered = await services.mission_tools().register(
                host,
                "register",
                name=f"private_{position}",
                description="Identify the independent tool build",
                source_path="tool.py",
                input_schema={"type": "object"},
                example_arguments={},
            )
            assert registered["smoke_test_passed"]
            assert host.run["run_id"] == run["run_id"]
            assert host.run["limits"] == run["limits"]
            assert host.kr_id == kr.kr_id and host.version == kr.version
            return Deliverable(
                kr_id=research_kr.kr_id,
                department="engineering",
                worker_role="tools_rd_lead",
                summary=f"Built and tested tool private_{position} in its private workspace.",
                artifact_ids=tuple(registered["artifact_ids"]),
            )

        monkeypatch.setattr(services, "_execute_worker", build)
        reports = await asyncio.gather(
            *(
                services.consult_tools_rd(
                    "engineering_head",
                    f"Build private capability {i}",
                    Constitution(),
                    parent,
                    f"consult-{i}",
                    kr,
                    mode="build_tool",
                )
                for i in range(2)
            )
        )
        managed = services.settings.data_dir.resolve() / "workspaces" / run["run_id"] / "tools-rd"
        assert len(workspaces) == 2 and workspaces[0] != workspaces[1]
        assert all(path.parent == managed for path in workspaces)
        assert all(path != external_workspace for path in workspaces)
        assert (external_workspace / "tool.py").read_text() == original
        assert set(external_workspace.iterdir()) == {external_workspace / "tool.py"}
        assert run["workspace_path"] == str(external_workspace)
        assert all(report["report_artifact_id"] for report in reports)
        entries = await services.mission_tools().list_tools()
        assert len(entries) == 2
        for entry in entries:
            result = await services.mission_tools().invoke(
                parent, f"verify-{entry['name']}", tool_id=entry["tool_id"], arguments={}
            )
            assert result["output"] == {"owner": int(entry["name"].rsplit("_", 1)[1])}
        assert (external_workspace / "tool.py").read_text() == original
        assert not requests


async def test_on_demand_rd_builds_tests_and_registers_tool_that_engineering_worker_uses(
    tmp_path, monkeypatch
):
    kr, work = assignment()
    work = work.model_copy(
        update={
            "specialist": EngineeringSpecialistSpec(
                name="Numeric pipeline specialist",
                instructions="Use the tested doubling tool and publish its result in output.json.",
                # Match the live lead's narrowed selection, which omitted write_file.
                tools=("run_mission_tool", "publish_file", "read_artifact"),
            )
        }
    )
    source = "import json,sys\na=json.load(sys.stdin)\nprint(json.dumps({'value':a['n']*2}))\n"
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    tool_id = None
    searched = []
    model_roles = []

    def script(body, requests):
        nonlocal tool_id
        if body.get("response_format"):
            payload = json.loads(body["messages"][-1]["content"])
            if "recorded_artifact_evidence" in payload:
                assert payload["deliverable"]["worker_role"] == "engineering_head"
                assignments = [
                    item
                    for item in payload["recorded_artifact_evidence"]
                    if item["kind"] == "agent_assignment"
                ]
                assert len(assignments) == 1
                proof = json.loads(assignments[0]["content"])
                assert proof["agent_id"] == worker_agent_id(run["run_id"], work)
                assert proof["display_name"] == "Numeric pipeline specialist"
                assert proof["work"]["specialist"] == work.specialist.model_dump(mode="json")
                assert proof["parent_agent_id"] == "engineering_head"
                assert proof["rd_consultations"][0]["mode"] == "build_tool"
                assert proof["rd_consultations"][0]["requested_by"] == "engineering_head"
                assert proof["rd_consultations"][0]["report_artifact_id"]
                assert "approved" not in proof
                return {"content": json.dumps(approve(payload["acceptance_criteria"]))}
            return extracted_deliverable(body)
        prompt = body["messages"][0]["content"]
        names = {item["function"]["name"] for item in body["tools"]}
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if prompt.startswith("You are tools_rd_lead"):
            assert "register_mission_tool" in names
            assert "consult_tools_rd" not in names and "run_mission_tool" not in names
            assert "JSON object from stdin" in body["messages"][-1]["content"] or results
            if not results:
                return {
                    "tool_calls": [
                        tool_call("search_market_data", {"query": "JSON stdin Python"}, "search")
                    ]
                }
            if len(results) == 1:
                return {
                    "tool_calls": [
                        tool_call("write_file", {"path": "double.py", "content": source}, "source")
                    ]
                }
            if len(results) == 2:
                return {
                    "tool_calls": [
                        tool_call(
                            "register_mission_tool",
                            {
                                "name": "double",
                                "description": "Double an integer",
                                "source_path": "double.py",
                                "input_schema": schema,
                                "example_arguments": {"n": 2},
                            },
                            "register",
                        )
                    ]
                }
            registered = json.loads(results[-1]["content"])
            assert registered["smoke_test_passed"]
            tool_id = registered["tool_id"]
            return {"content": f"Registered tested double tool {tool_id}."}
        if prompt.startswith("You are a department head"):
            assert "register_mission_tool" not in names
            if not results:
                return {
                    "tool_calls": [
                        tool_call(
                            "consult_tools_rd",
                            {
                                "requirement": "Build a tested integer doubling tool",
                                "mode": "build_tool",
                            },
                            "consult",
                        )
                    ]
                }
            consultation = json.loads(results[0]["content"])
            assert consultation["artifact_id"]
            assert consultation["result"]["report"].strip()
            assert consultation["result"]["mode"] == "build_tool"
            assert consultation["result"]["artifact_ids"]
            assert consultation["result"]["tools"][0]["tool_id"] == tool_id
            return {"content": TacticalPlan(work_packages=(work,)).model_dump_json()}
        assert "Numeric pipeline specialist" in prompt
        assert "consult_tools_rd" not in names and "register_mission_tool" not in names
        assert names == set(work.specialist.tools) | ENGINEERING_CORE_TOOL_NAMES
        assert not names & {"run_command", "validate_code_syntax", "read_file", "read_web_page"}
        assert "Save required run_mission_tool output files with write_file" in prompt
        assert tool_id in prompt
        if not results:
            return {
                "tool_calls": [
                    tool_call(
                        "run_mission_tool", {"tool_id": tool_id, "arguments": {"n": 21}}, "invoke"
                    )
                ]
            }
        if len(results) == 1:
            output = json.loads(results[0]["content"])["output"]
            assert output == {"value": 42}
            return {
                "tool_calls": [
                    tool_call(
                        "write_file",
                        {"path": "output.json", "content": json.dumps(output)},
                        "output",
                    )
                ]
            }
        return {"content": "Published output.json with the tested tool's result."}

    async with services_with_provider(tmp_path, script) as (
        services,
        storage,
        run,
        requests,
        workspace,
    ):
        model_for = services.model_for

        def recorded_model_role(role=None):
            model_roles.append(role)
            return model_for(role)

        async def research(kind, arguments, call_id):
            searched.append((kind, arguments))
            return {"sources": ["https://docs.python.org/3/library/json.html"]}

        services.model_for = recorded_model_role
        monkeypatch.setattr(services, "_invoke_mcp", research)
        packages = await services.plan_work(kr, Constitution(), [], "")
        assert len(await services.mission_tools().list_tools()) == 1
        result = await services.execute(packages[0], kr, Constitution(), [], "", 0)
        assert result.worker_role == worker_agent_id(run["run_id"], work)
        aggregate = result.model_copy(update={"worker_role": "engineering_head"})
        evaluation = await services.evaluate(aggregate, kr.acceptance_criteria, Constitution())
        assert gate_approved(aggregate, evaluation, kr.acceptance_criteria)
        recorded = await storage.list_artifacts(run["run_id"])
        proofs = [item for item in recorded if item["kind"] == "agent_assignment"]
        assert len(proofs) == 1 and proofs[0]["artifact_id"] in result.artifact_ids
        host = WorkerHostTools(
            storage,
            services.artifacts,
            run,
            kr_id=kr.kr_id,
            version=kr.version,
            department="engineering",
            epoch=0,
            role=result.worker_role,
            emit=services.emit,
            work_package_id=work.work_package_id,
            attempt=work.execution_attempt,
        )
        replay = await services._record_agent_assignment(work, kr, host)
        assert replay["artifact_id"] == proofs[0]["artifact_id"]
        assert (
            len(
                [
                    item
                    for item in await storage.list_artifacts(run["run_id"])
                    if item["kind"] == "agent_assignment"
                ]
            )
            == 1
        )
        assert json.loads((workspace / "output.json").read_text()) == {"value": 42}
        assert len(searched) == 1
        assert model_roles == [
            "engineering_head",
            "tools_rd_lead",
            "tools_rd_lead",
            work.role,
            work.role,
            "engineering_gatekeeper",
        ]
        commands = [item for item in storage.operations.values() if item["kind"] == "command"]
        assert len(commands) == 2 and all(item["status"] == "done" for item in commands)
        assert len(requests) == 12  # Planning 2, R&D 5, worker 4, one complete KR review.
        rd_events = [item for item in storage.events if item["agent_id"] == "tools_rd_lead"]
        assert len(rd_events) > 2
        assert all(item["data"]["display_name"] == "Tools R&D Lead" for item in rd_events)
        assert all(item["data"]["parent_agent_id"] == "engineering_head" for item in rd_events)


async def record_public_rd_result(services, kr, call_id, *, caller="engineering_head"):
    parent = services._planning_host(caller, kr)
    rd_host = WorkerHostTools(
        services.storage,
        services.artifacts,
        services.run,
        kr_id=kr.kr_id if kr else "planner-tools",
        version=kr.version if kr else 1,
        department="engineering",
        epoch=0,
        role="tools_rd_lead",
        emit=services.emit,
        work_package_id=call_id,
    )
    report = await rd_host.write_file(
        "report", f"{call_id}/report.md", "Public report body; PRIVATE_BODY_SENTINEL"
    )
    result = ToolsResearchResult(
        report=f"Verified public findings for {call_id}",
        artifact_ids=(report["artifact_id"],),
        report_artifact_id=report["artifact_id"],
        mode="research",
        requested_by=caller,
        tools=({"private_detail": "PRIVATE_TOOL_SENTINEL"},),
    )

    async def recorded():
        return result.model_dump(mode="json")

    consultation = await parent.record_research(
        call_id, "tools_rd_consultation", {"mode": "research", "requirement": call_id}, recorded
    )
    return consultation, report


async def test_assignment_provenance_filters_other_krs_and_versions_and_preserves_planner_refs(
    tmp_path,
):
    kr, work = assignment()
    kr = kr.model_copy(update={"version": 2})
    work = work.model_copy(
        update={
            "specialist": EngineeringSpecialistSpec(
                name="Verification specialist", instructions="Verify the requested output."
            )
        }
    )
    async with services_with_provider(tmp_path, lambda *_: {}) as (
        services,
        storage,
        run,
        requests,
        _,
    ):
        current, _ = await record_public_rd_result(services, kr, "current")
        planner, _ = await record_public_rd_result(services, None, "planner", caller="planner")
        other_kr = kr.model_copy(update={"kr_id": "different-kr"})
        other, _ = await record_public_rd_result(services, other_kr, "other")
        stale, _ = await record_public_rd_result(
            services, kr.model_copy(update={"version": 1}), "stale"
        )
        host = WorkerHostTools(
            storage,
            services.artifacts,
            run,
            kr_id=kr.kr_id,
            version=kr.version,
            department="engineering",
            epoch=0,
            role=worker_agent_id(run["run_id"], work),
            emit=services.emit,
            work_package_id=work.work_package_id,
        )
        saved = await services._record_agent_assignment(work, kr, host)
        metadata, content = await services.artifacts.read(saved["artifact_id"], limit=None)
        proof = json.loads(content)
        refs = {item["consultation_artifact_id"] for item in proof["rd_consultations"]}
        assert refs == {current["artifact_id"], planner["artifact_id"]}
        assert other["artifact_id"] not in refs and stale["artifact_id"] not in refs
        assert "PRIVATE_BODY_SENTINEL" not in content and "PRIVATE_TOOL_SENTINEL" not in content
        assert metadata["scope"] == host.scope and metadata["version"] == kr.version
        assert (
            saved["artifact_id"]
            == (await services._record_agent_assignment(work, kr, host))["artifact_id"]
        )
        assert not requests


async def test_assignment_provenance_rejects_corrupted_report_evidence(tmp_path):
    kr, work = assignment()
    work = work.model_copy(
        update={
            "specialist": EngineeringSpecialistSpec(
                name="Verifier", instructions="Verify the requested output."
            )
        }
    )
    async with services_with_provider(tmp_path, lambda *_: {}) as (services, storage, run, _, _):
        _, report = await record_public_rd_result(services, kr, "corrupted")
        metadata = await storage.get_artifact(report["artifact_id"])
        Path(metadata["path"]).write_text("Altered report content")
        host = WorkerHostTools(
            storage,
            services.artifacts,
            run,
            kr_id=kr.kr_id,
            version=kr.version,
            department="engineering",
            epoch=0,
            role=worker_agent_id(run["run_id"], work),
            emit=services.emit,
            work_package_id=work.work_package_id,
        )
        with pytest.raises(EscalationSignal) as error:
            await services._record_agent_assignment(work, kr, host)
        assert error.value.kind == "missing_resource"
        assert not any(
            item["kind"] == "agent_assignment"
            for item in await storage.list_artifacts(run["run_id"])
        )


@pytest.mark.parametrize("kind", ["agent_assignment", "mission_tool_support"])
async def test_process_metadata_alone_cannot_replace_substantive_worker_output(tmp_path, kind):
    kr, work = assignment()

    def script(body, requests):
        return {"content": json.dumps(approve(kr.acceptance_criteria))}

    async with services_with_provider(tmp_path, script) as (services, _, _, _, _):
        artifact = await services.artifacts.save(
            "process-proof.json", '{"actor":"created"}', kind=kind
        )
        deliverable = Deliverable(
            kr_id=kr.kr_id,
            department="engineering",
            worker_role=work.role,
            summary="Claims completion with process metadata only.",
            artifact_ids=(artifact["artifact_id"],),
        )
        evaluation = await services.evaluate(deliverable, kr.acceptance_criteria, Constitution())
        assert evaluation.passed_kr_criteria  # Deliberately optimistic semantic judge.
        assert not evaluation.deterministic_checks_passed
        assert not gate_approved(deliverable, evaluation, kr.acceptance_criteria)
