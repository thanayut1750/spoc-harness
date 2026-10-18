"""Exercise the real LangChain worker/tool loop with a mocked provider transport."""

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from langchain_core.tools import ToolException, tool
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
        finish_reason = message.pop("_finish_reason", "stop")
        return httpx.Response(
            200,
            json={
                "id": f"response-{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "glm-5.3-flash",
                "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
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
                    artifact_ids=(artifact_id,) if approved_dependency else (),
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
        if approved_dependency:
            result = await services.execute(work, kr, Constitution(), [dependency], "", 0)
            assert result.artifact_ids == (artifact_id,)
        else:
            with pytest.raises(EscalationSignal) as error:
                await services.execute(work, kr, Constitution(), [], "", 0)
            assert error.value.kind == "missing_deliverable"
        tool_result = next(
            message["content"] for message in requests[1]["messages"] if message["role"] == "tool"
        )
        assert ("Other assignment evidence" in tool_result) is approved_dependency
        assert ("outside this assignment" in tool_result) is not approved_dependency
        assert (await storage.get_run(run["run_id"]))["tool_calls"] == 1


@pytest.mark.parametrize("malformed_suffix", [False, True])
async def test_syntax_gate_checks_complete_source_beyond_prompt_excerpt(tmp_path, malformed_suffix):
    kr, _ = assignment()
    criteria = ("The complete Python source has valid syntax",)

    def script(body, requests):
        return {"content": json.dumps(approve(criteria))}

    async with services_with_provider(tmp_path, script) as (services, _, _, requests, _):
        source = (
            ("#" + "x" * 70000 + "\nbroken = '\n")
            if malformed_suffix
            else ("value = '" + "x" * 70000 + "'\n")
        )
        artifact = await services.artifacts.save("large.py", source, kind="source", kr_id=kr.kr_id)
        deliverable = Deliverable(
            kr_id=kr.kr_id,
            department="engineering",
            worker_role="backend_coder",
            summary="Large Python source",
            artifact_ids=(artifact["artifact_id"],),
        )
        result = await services.evaluate(deliverable, criteria, Constitution())
        assert result.deterministic_checks_passed is not malformed_suffix
        # Complete local validation must not remove the separate model context cap.
        payload = json.loads(requests[0]["messages"][-1]["content"])
        if payload["recorded_artifact_evidence"]:
            assert len(payload["recorded_artifact_evidence"][0]["content"]) <= 12000


async def test_mcp_execution_error_is_a_blocker_not_research_evidence(tmp_path, monkeypatch):
    kr, work = assignment()
    kr = kr.model_copy(update={"target_department": "research"})
    work = work.model_copy(update={"role": "market_researcher"})

    def script(body, requests):
        return {"tool_calls": [tool_call("search_market_data", {"query": "public research"})]}

    @tool
    async def remote_search(search_query: str) -> str:
        """A remote tool with an MCP-style handled execution error."""
        raise ToolException("Tool quota is unavailable")

    remote_search.handle_tool_error = True
    async with services_with_provider(tmp_path, script) as (services, storage, run, _, _):

        async def remote(kind):
            return remote_search

        monkeypatch.setattr(services, "_mcp_tool", remote)
        with pytest.raises(EscalationSignal) as error:
            await services.execute(work, kr, Constitution(), [], "", 0)
        assert error.value.kind == "missing_resource"
        assert not await storage.list_artifacts(run["run_id"])


async def test_empty_truncated_answer_continues_with_saved_tools_and_actual_manifest(tmp_path):
    kr, work = assignment()

    def script(body, requests):
        if body.get("response_format"):
            payload = json.loads(body["messages"][-1]["content"])
            assert payload["recorded_tool_artifacts"][0]["name"] == "answer.py"
            return {
                "content": json.dumps(
                    {
                        "kr_id": kr.kr_id,
                        "department": "engineering",
                        "worker_role": work.role,
                        "summary": "Wrote the Python answer",
                        "artifact_ids": [],
                        "evidence": [],
                        "confidence_score": 0.5,
                    }
                )
            }
        tools = [item for item in body["messages"] if item["role"] == "tool"]
        if not tools:
            return {
                "tool_calls": [
                    tool_call("write_file", {"path": "answer.py", "content": "answer = 42\n"})
                ]
            }
        if len(requests) == 2:
            return {"content": "", "_finish_reason": "length"}
        assert any(
            "Continue from the tool results" in item.get("content", "")
            for item in body["messages"]
            if item["role"] == "user"
        )
        assert tools[0]["tool_call_id"] == "tool-1"
        return {"content": "Wrote answer.py; the saved artifact contains answer = 42."}

    async with services_with_provider(tmp_path, script) as (services, storage, run, requests, _):
        result = await services.execute(work, kr, Constitution(), [], "", 0)
        assert len(requests) == 4
        assert len(storage.operations) == 1  # Continuation does not repeat the write.
        assert len(result.artifact_ids) == 1  # Actual manifest repairs a dropped model reference.
        _, content = await services.artifacts.read(result.artifact_ids[0])
        assert content == "answer = 42\n"


async def test_repeated_empty_response_is_explicit_and_never_saved_as_deliverable(tmp_path):
    kr, work = assignment()

    def script(body, requests):
        assert not body.get("response_format"), "Empty output must not reach extraction"
        return {"content": "", "_finish_reason": "length"}

    async with services_with_provider(tmp_path, script) as (services, storage, run, requests, _):
        with pytest.raises(EscalationSignal) as error:
            await services.execute(work, kr, Constitution(), [], "", 0)
        assert error.value.kind == "incomplete_worker_output"
        assert len(requests) == 2
        assert not await storage.list_artifacts(run["run_id"])


async def test_corrected_source_and_check_supersede_broken_snapshots(tmp_path):
    kr, work = assignment()
    observed = []

    def script(body, requests):
        if body.get("response_format"):
            payload = json.loads(body["messages"][-1]["content"])
            if "worker_result" not in payload:
                assert [
                    item["exit_code"]
                    for item in payload["recorded_check_history"]
                    if item.get("command")
                ] == [1, 0]
                assert [
                    item["passed"]
                    for item in payload["recorded_check_history"]
                    if item.get("verification_tool")
                ] == [False, True]
                return {"content": json.dumps(approve(kr.acceptance_criteria))}
            return {
                "content": json.dumps(
                    {
                        "kr_id": kr.kr_id,
                        "department": "engineering",
                        "worker_role": work.role,
                        "summary": "Corrected and verified answer.py",
                        "artifact_ids": observed,
                        "evidence": ["The final Python execution printed verified and exited 0"],
                    }
                )
            }
        tools = [json.loads(item["content"]) for item in body["messages"] if item["role"] == "tool"]
        observed[:] = list(
            dict.fromkeys(
                item
                for result in tools
                for item in (
                    [result["artifact_id"]]
                    if "artifact_id" in result
                    else result.get("artifact_ids", [])
                )
            )
        )
        actions = [
            tool_call("write_file", {"path": "answer.py", "content": "def broken(\n"}, "broken"),
            tool_call("validate_code_syntax", {"path": "answer.py"}, "syntax-failed"),
            tool_call("run_command", {"command": "python3 answer.py"}, "failed-check"),
            tool_call(
                "write_file",
                {"path": "answer.py", "content": "answer = 42\nprint('verified')\n"},
                "corrected",
            ),
            tool_call("validate_code_syntax", {"path": "answer.py"}, "syntax-passed"),
            tool_call("run_command", {"command": "python3 answer.py"}, "passed-check"),
        ]
        return (
            {"tool_calls": [actions[len(tools)]]}
            if len(tools) < len(actions)
            else {"content": "Corrected the source and verified it successfully."}
        )

    async with services_with_provider(tmp_path, script) as (services, storage, run, _, _):
        result = await services.execute(work, kr, Constitution(), [], "", 0)
        evaluation = await services.evaluate(result, kr.acceptance_criteria, Constitution())
        assert evaluation.deterministic_checks_passed
        assert len(result.artifact_ids) == 4
        history = await storage.list_artifacts(run["run_id"])
        old_source = next(item for item in history if item["kind"] == "source")
        assert old_source["artifact_id"] not in result.artifact_ids
        assert any(item.get("exit_code") == 1 for item in history)


async def test_no_tool_evidence_never_creates_an_empty_submission(tmp_path):
    kr, work = assignment()

    def script(body, requests):
        if body.get("response_format"):
            return {
                "content": json.dumps(
                    {
                        "kr_id": kr.kr_id,
                        "department": "engineering",
                        "worker_role": work.role,
                        "summary": "Claims work is complete",
                        "artifact_ids": [],
                        "evidence": [],
                    }
                )
            }
        return {"content": "Done."}

    async with services_with_provider(tmp_path, script) as (services, storage, run, _, _):
        with pytest.raises(EscalationSignal) as error:
            await services.execute(work, kr, Constitution(), [], "", 0)
        assert error.value.kind == "missing_deliverable"
        assert not await storage.list_artifacts(run["run_id"])


async def test_large_reader_response_is_paged_and_full_source_remains_available(
    tmp_path, monkeypatch
):
    kr, work = assignment()
    kr = kr.model_copy(update={"target_department": "research"})
    work = work.model_copy(update={"role": "market_researcher"})
    full_source = {"content": "A" * 75000 + "EXACT_SOURCE_END"}
    artifact_id = None

    def script(body, requests):
        nonlocal artifact_id
        if body.get("response_format"):
            return {
                "content": json.dumps(
                    {
                        "kr_id": kr.kr_id,
                        "department": "research",
                        "worker_role": work.role,
                        "summary": "Read the full source through bounded pages",
                        "artifact_ids": [],
                        "evidence": [],
                    }
                )
            }
        tools = [item for item in body["messages"] if item["role"] == "tool"]
        if not tools:
            return {
                "tool_calls": [
                    tool_call("read_web_page", {"url": "https://example.com/public"}, "reader")
                ]
            }
        if len(tools) == 1:
            assert len(tools[0]["content"]) < 13000
            result = json.loads(tools[0]["content"])
            assert result["result"]["truncated"]
            artifact_id = result["artifact_id"]
            return {
                "tool_calls": [
                    tool_call(
                        "read_artifact",
                        {"artifact_id": artifact_id, "offset": 75000, "limit": 1000},
                        "page",
                    )
                ]
            }
        page = json.loads(tools[-1]["content"])
        assert "EXACT_SOURCE_END" in page["content"]
        assert page["next_offset"] is None
        return {"content": "The source was read without repeating the web request."}

    async with services_with_provider(tmp_path, script) as (services, _, _, _, _):

        async def invoke(*args):
            return full_source

        monkeypatch.setattr(services, "_invoke_mcp", invoke)
        result = await services.execute(work, kr, Constitution(), [], "", 0)
        assert result.artifact_ids == (artifact_id,)
        _, content = await services.artifacts.read(artifact_id, limit=None)
        assert "EXACT_SOURCE_END" in content


async def test_empty_file_or_log_cannot_satisfy_substantive_evidence(tmp_path):
    kr, _ = assignment()
    async with services_with_provider(
        tmp_path, lambda body, requests: {"content": json.dumps(approve(kr.acceptance_criteria))}
    ) as (services, _, _, _, _):
        empty = await services.artifacts.save(
            "empty.stderr.txt", "", kind="command_log", exit_code=0
        )
        deliverable = Deliverable(
            kr_id=kr.kr_id,
            department="engineering",
            worker_role="backend_coder",
            summary="Claims success",
            artifact_ids=(empty["artifact_id"],),
        )
        result = await services.evaluate(deliverable, kr.acceptance_criteria, Constitution())
        assert not result.deterministic_checks_passed


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
