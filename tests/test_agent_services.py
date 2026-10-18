"""Exercise the real LangChain worker/tool loop with a mocked provider transport."""

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from openai import AsyncOpenAI

from org_harness.agent_services import AgentServices
from org_harness.config import Settings
from org_harness.models import (
    Constitution,
    Deliverable,
    EscalationSignal,
    KeyResult,
    StrategicObjective,
    WorkPackage,
)
from org_harness.providers import ZaiChatModel
from org_harness.runtime import build_graph, gate_approved, initial_state, runtime_config
from org_harness.storage import MemoryStorage
from org_harness.tools import HostTools


def assignment():
    key_result = KeyResult(
        kr_id="implementation",
        description="Create and verify Python output",
        acceptance_criteria=("Python assertion succeeds",),
        target_department="engineering",
    )
    work = WorkPackage(
        work_package_id="implementation-work",
        kr_id=key_result.kr_id,
        role="backend_coder",
        task=key_result.description,
        acceptance_criteria=key_result.acceptance_criteria,
    )
    return key_result, work


def tool_call(name, arguments, call_id="tool-1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def approve(criteria):
    return {
        "passed_constitution": True,
        "passed_kr_criteria": True,
        "score": 1,
        "feedback": "Semantic judge says all criteria passed",
        "criterion_results": dict.fromkeys(criteria, True),
        "recommended_action": "approve",
    }


@asynccontextmanager
async def services_with_provider(tmp_path, script, *, limits=None):
    storage = MemoryStorage()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run = await storage.create_run(
        {
            "user_request": "Implement and verify",
            "workspace_path": str(workspace),
            **({"limits": limits} if limits else {}),
        }
    )
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", harness_test_mode=False)
    services = AgentServices(settings, storage, run)
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        message = {
            "role": "assistant",
            "content": None,
            "reasoning_content": "private-provider-data",
        }
        message.update(script(body, requests))
        return httpx.Response(
            200,
            json={
                "id": f"response-{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "glm-5.3-flash",
                "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    client = AsyncOpenAI(
        api_key="fixture-key",
        base_url="https://provider.invalid/v4",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    services.model = ZaiChatModel(async_client=client)
    try:
        yield services, storage, run, requests, workspace
    finally:
        await services.close()


async def test_real_create_agent_executes_tools_and_preserves_reasoning_roundtrip(tmp_path):
    key_result, work = assignment()
    artifact_ids = []

    def script(body, requests):
        if body.get("response_format"):
            return {
                "content": json.dumps(
                    {
                        "kr_id": key_result.kr_id,
                        "department": "engineering",
                        "worker_role": work.role,
                        "summary": "Created Python and ran its assertion successfully",
                        "artifact_ids": artifact_ids,
                        "evidence": ["Python exited 0"],
                        "confidence_score": 1,
                    }
                )
            }
        tool_results = [message for message in body["messages"] if message["role"] == "tool"]
        if not tool_results:
            return {
                "tool_calls": [
                    tool_call(
                        "write_file",
                        {
                            "path": "check.py",
                            "content": "assert 2 + 2 == 4\nprint('verified')\n",
                        },
                        "write-call",
                    )
                ]
            }
        if len(tool_results) == 1:
            artifact_ids.append(json.loads(tool_results[0]["content"])["artifact_id"])
            return {
                "tool_calls": [
                    tool_call("run_command", {"command": "python3 check.py"}, "run-call")
                ]
            }
        artifact_ids.extend(json.loads(tool_results[-1]["content"])["artifact_ids"])
        return {
            "content": "The Python check succeeded. Recorded artifacts: " + ",".join(artifact_ids)
        }

    async with services_with_provider(tmp_path, script) as (
        services,
        storage,
        run,
        requests,
        workspace,
    ):
        result = await services.execute(work, key_result, Constitution(), [], "", 0)
        assert result.kr_id == key_result.kr_id
        assert result.worker_role == work.role
        assert (workspace / "check.py").read_text().startswith("assert 2 + 2")
        assert len(result.artifact_ids) == 3
        commands = [item for item in storage.operations.values() if item["kind"] == "command"]
        assert len(commands) == 1
        assert commands[0]["result"]["exit_code"] == 0
        assert commands[0]["result"]["stdout"].strip() == "verified"
        assert len(requests) == 4  # Three agent turns and typed deliverable extraction.
        assert any(
            message.get("reasoning_content") == "private-provider-data"
            for message in requests[1]["messages"]
            if message["role"] == "assistant"
        )
        assert any(
            message.get("tool_call_id") == "write-call" for message in requests[1]["messages"]
        )
        assert "tools" in requests[0]
        assert requests[-1]["response_format"] == {"type": "json_object"}


async def test_escalation_preempts_other_tools_from_same_model_response(tmp_path):
    key_result, work = assignment()

    def script(body, requests):
        return {
            "tool_calls": [
                tool_call(
                    "write_file", {"path": "must-not-exist.txt", "content": "forbidden"}, "write"
                ),
                tool_call(
                    "escalate_blocker",
                    {
                        "reason": "The task conflicts with the constitution",
                        "constitution_violation": True,
                    },
                    "escalate",
                ),
            ]
        }

    async with services_with_provider(tmp_path, script) as (
        services,
        storage,
        run,
        requests,
        workspace,
    ):
        with pytest.raises(EscalationSignal) as error:
            await services.execute(work, key_result, Constitution(), [], "", 0)
        assert error.value.kind == "constitution_violation"
        assert not (workspace / "must-not-exist.txt").exists()
        assert not storage.operations
        assert len(requests) == 1


async def test_per_worker_model_limit_is_explicit_blocker_not_a_deliverable(tmp_path):
    key_result, work = assignment()

    def script(body, requests):
        return {"tool_calls": [tool_call("read_file", {"path": "input.txt"}, "read")]}

    async with services_with_provider(tmp_path, script, limits={"worker_model_calls": 1}) as (
        services,
        storage,
        run,
        requests,
        workspace,
    ):
        (workspace / "input.txt").write_text("Input")
        with pytest.raises(EscalationSignal) as error:
            await services.execute(work, key_result, Constitution(), [], "", 0)
        assert error.value.kind == "limit_exceeded"
        assert len(requests) == 1


async def test_semantic_judge_cannot_approve_failed_command_evidence(tmp_path):
    key_result, _ = assignment()

    def script(body, requests):
        return {"content": json.dumps(approve(key_result.acceptance_criteria))}

    async with services_with_provider(tmp_path, script) as (
        services,
        storage,
        run,
        requests,
        workspace,
    ):
        host = HostTools(
            storage,
            services.artifacts,
            run,
            kr_id=key_result.kr_id,
            department="engineering",
            epoch=0,
            role="backend_coder",
            emit=services.emit,
        )
        failed = await host.run_command("failure", "printf 'bad evidence'; exit 7")
        deliverable = Deliverable(
            kr_id=key_result.kr_id,
            department="engineering",
            worker_role="backend_coder",
            summary="Claimed command success",
            artifact_ids=tuple(failed["artifact_ids"]),
            evidence=("Claimed success",),
        )
        result = await services.evaluate(
            deliverable, key_result.acceptance_criteria, Constitution()
        )
        assert result.passed_kr_criteria  # The scripted semantic judge is intentionally wrong.
        assert not result.deterministic_checks_passed
        assert not gate_approved(deliverable, result, key_result.acceptance_criteria)


async def test_self_report_artifact_alone_is_not_deterministic_evidence(tmp_path):
    key_result, _ = assignment()

    def script(body, requests):
        return {"content": json.dumps(approve(key_result.acceptance_criteria))}

    async with services_with_provider(tmp_path, script) as (
        services,
        storage,
        run,
        requests,
        workspace,
    ):
        artifact = await services.artifacts.save(
            "claimed-deliverable.json",
            '{"summary":"It works"}',
            kind="deliverable",
            kr_id=key_result.kr_id,
            department="engineering",
        )
        deliverable = Deliverable(
            kr_id=key_result.kr_id,
            department="engineering",
            worker_role="backend_coder",
            summary="Claimed success",
            artifact_ids=(artifact["artifact_id"],),
        )
        result = await services.evaluate(
            deliverable, key_result.acceptance_criteria, Constitution()
        )
        assert not result.deterministic_checks_passed
        assert not gate_approved(deliverable, result, key_result.acceptance_criteria)


@pytest.mark.parametrize("approved_dependency", [False, True])
async def test_artifact_reads_require_assignment_or_approved_dependency(
    tmp_path, approved_dependency
):
    kr, work = assignment()
    artifact_id = ""

    def script(body, requests):
        if body.get("response_format"):
            return {
                "content": Deliverable(
                    kr_id=kr.kr_id,
                    department="engineering",
                    worker_role=work.role,
                    summary="Inspected input",
                ).model_dump_json()
            }
        if len(requests) == 1:
            return {"tool_calls": [tool_call("read_artifact", {"artifact_id": artifact_id})]}
        return {"content": "Input inspection complete"}

    async with services_with_provider(tmp_path, script) as (services, storage, run, requests, _):
        artifact = await services.artifacts.save(
            "research.md",
            "Other assignment evidence",
            kr_id="other-kr",
            department="research",
            kind="source",
        )
        artifact_id = artifact["artifact_id"]
        dependency = Deliverable(
            kr_id="other-kr",
            department="research",
            worker_role="market_researcher",
            summary="Approved research",
            artifact_ids=(artifact_id,),
        )
        await services.execute(
            work, kr, Constitution(), [dependency] if approved_dependency else [], "", 0
        )
        tool_result = next(
            message["content"] for message in requests[1]["messages"] if message["role"] == "tool"
        )
        assert ("Other assignment evidence" in tool_result) is approved_dependency
        assert ("outside this assignment" in tool_result) is not approved_dependency
        assert (await storage.get_run(run["run_id"]))["tool_calls"] == 1


async def test_real_worker_tool_checkpoint_survives_process_restart(tmp_path):
    key_result, work = assignment()
    crashed = False
    plan_calls = 0
    tactical_calls = 0
    recovered_tool_messages = []

    def script(body, requests):
        if body.get("response_format"):
            payload = json.loads(body["messages"][-1]["content"])
            if "worker_result" not in payload:
                return {"content": json.dumps(approve(key_result.acceptance_criteria))}
            return {
                "content": json.dumps(
                    {
                        "kr_id": key_result.kr_id,
                        "department": "engineering",
                        "worker_role": work.role,
                        "summary": "Created a Python artifact",
                        "artifact_ids": recovered_tool_messages,
                        "evidence": ["The Python artifact parses"],
                        "confidence_score": 1,
                    }
                )
            }
        tool_results = [message for message in body["messages"] if message["role"] == "tool"]
        if not tool_results:
            return {
                "tool_calls": [
                    tool_call(
                        "write_file",
                        {
                            "path": "durable.py",
                            "content": "assert 1 + 1 == 2\n",
                        },
                        "durable-write",
                    )
                ]
            }
        recovered_tool_messages[:] = [json.loads(tool_results[0]["content"])["artifact_id"]]
        return {"content": "Created durable Python artifact " + recovered_tool_messages[0]}

    async with services_with_provider(tmp_path, script) as (
        services,
        storage,
        run,
        requests,
        workspace,
    ):

        async def plan(request, constitution):
            nonlocal plan_calls
            plan_calls += 1
            return [
                StrategicObjective(
                    objective_id="mission", title="Mission", key_results=(key_result,)
                )
            ]

        async def plan_work(*args):
            nonlocal tactical_calls
            tactical_calls += 1
            return [work]

        async def synthesize(*args):
            return "Completed using recovered evidence."

        model_request = services.model_request

        async def crash_after_tool(request):
            nonlocal crashed
            if storage.operations and not crashed:
                crashed = True
                raise RuntimeError("Simulated crash after completed host tool")
            return await model_request(request)

        services.plan = plan
        services.plan_work = plan_work
        services.synthesize = synthesize
        services.model_request = crash_after_tool
        saver = InMemorySaver()
        config = runtime_config(run["run_id"])
        graph = build_graph(services, checkpointer=saver)
        with pytest.raises(RuntimeError, match="Simulated crash"):
            await graph.ainvoke(initial_state(run["run_id"], "Implement", Constitution()), config)
        assert (workspace / "durable.py").exists()
        assert len(storage.operations) == 1
        restored = build_graph(services, checkpointer=saver)
        result = await restored.ainvoke(None, config)
        assert result["status"] == "completed"
        assert plan_calls == tactical_calls == 1
        assert len(storage.operations) == 1
        assert recovered_tool_messages
        # The agent resumes its private tool result, rather than beginning with
        # an empty conversation. The executive remains free of message history.
        assert any(message["role"] == "tool" for message in requests[1]["messages"])
        assert "messages" not in result
