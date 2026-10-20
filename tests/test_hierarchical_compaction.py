"""Oversized private progress stays bounded, complete, and durably resumable."""

import json
import re

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, get_buffer_string
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from test_agent_services import assignment, services_with_provider, tool_call
from test_agent_session_recovery import (
    UNLIMITED,
    execute_graph,
    operations,
    private_snapshots,
    service_factory,
)
from test_dynamic_services import extracted_deliverable

from org_harness.agent_services import AgentServices
from org_harness.agent_sessions import (
    SUMMARY_INPUT_BYTES,
    SUMMARY_REDUCE_BYTES,
    ProgressCompactionMiddleware,
    compact_progress,
    split_progress,
)
from org_harness.autonomy import AutonomousCheckpointYield
from org_harness.config import Settings
from org_harness.models import (
    Constitution,
    RunCreate,
    StrategicObjective,
    StrategicPlan,
    TacticalPlan,
)
from org_harness.runtime import runtime_config
from org_harness.storage import PostgresStorage
from org_harness.worker import Worker, migrate


def progress_payload(body):
    if body.get("response_format") and "Compact private task progress" in str(
        body["messages"][0]["content"]
    ):
        return json.loads(body["messages"][1]["content"])["private_progress"]
    return None


def evidence_report(progress):
    markers = sorted(set(re.findall(r"EVIDENCE_\d+|ORIGINAL_REQUIREMENT", progress)))
    return {"content": json.dumps({"report": "Recorded facts: " + " ".join(markers)})}


@pytest.mark.parametrize("limit", [4, 7, 47999, SUMMARY_INPUT_BYTES])
def test_progress_fragments_preserve_every_unicode_byte_and_boundary(limit):
    original = 'Original requirement: 🧭研究 "quoted" \\ evidence\n' * 1700
    chunks = split_progress(original, limit)
    assert "".join(chunks) == original
    assert all(0 < len(chunk.encode("utf-8")) <= limit for chunk in chunks)
    assert b"".join(chunk.encode("utf-8") for chunk in chunks) == original.encode("utf-8")


async def test_expanding_unicode_reports_still_reduce_to_one_bounded_result(tmp_path):
    calls = []

    def script(body, requests):
        progress = progress_payload(body)
        assert progress is not None
        calls.append(progress)
        # A maximum-size UTF-8 report can expand a short last input fragment.
        return {"content": json.dumps({"report": "🧭" * 6000})}

    async with services_with_provider(tmp_path, script, limits=UNLIMITED) as (
        services,
        storage,
        run,
        requests,
        _,
    ):
        services.agent_checkpointer = InMemorySaver()
        original = "a" * (SUMMARY_INPUT_BYTES * 2 + 1)
        report = await compact_progress(services, "backend_coder", original)
        assert report == "🧭" * 6000
        assert len(calls) == 5  # Three maps and two reductions, with no expanding loop.
        assert "".join(calls[:3]) == original
        assert all(len(value.encode("utf-8")) <= SUMMARY_INPUT_BYTES for value in calls[:3])
        assert all(len(value.encode("utf-8")) <= SUMMARY_REDUCE_BYTES for value in calls[3:])
        assert len(calls[3].encode("utf-8")) > SUMMARY_INPUT_BYTES
        current = await storage.get_run(run["run_id"])
        assert current["model_calls"] == len(requests) == 5
        # Replaying the completed parent node reuses the final private receipt.
        assert await compact_progress(services, "backend_coder", original) == report
        assert len(requests) == 5


async def test_compaction_yields_after_32_calls_and_resumes_fresh_services_without_recharge(
    tmp_path,
):
    calls = []

    def script(body, requests):
        progress = progress_payload(body)
        assert progress is not None
        calls.append(progress)
        return evidence_report(progress)

    async with services_with_provider(tmp_path, script, limits=UNLIMITED) as (
        provider,
        storage,
        run,
        requests,
        _,
    ):
        saver = InMemorySaver()
        original = "".join(
            (f"EVIDENCE_{index:03} " + "x" * SUMMARY_INPUT_BYTES)[:SUMMARY_INPUT_BYTES]
            for index in range(33)
        )
        for invocation in range(3):
            services = AgentServices(
                provider.settings, storage, await storage.get_run(run["run_id"])
            )
            services.model_for = lambda actor=None: provider.model
            services.agent_checkpointer = saver
            try:
                if invocation < 2:
                    with pytest.raises(AutonomousCheckpointYield) as raised:
                        await compact_progress(services, "backend_coder", original)
                    assert not raised.value.recoverable_failure
                    assert len(requests) == (invocation + 1) * 32
                else:
                    report = await compact_progress(services, "backend_coder", original)
            finally:
                await services.close()
        assert len(calls) == 65  # 33 maps, 32 pairwise reductions.
        assert "".join(calls[:33]) == original
        assert set(re.findall(r"EVIDENCE_\d+", report)) == {
            f"EVIDENCE_{index:03}" for index in range(33)
        }
        current = await storage.get_run(run["run_id"])
        assert current["model_calls"] == len(requests) == 65


def test_unresolved_parallel_tool_calls_are_never_removed_from_retained_history():
    # An incomplete call must remain paired with its eventual ToolMessage.
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    middleware = ProgressCompactionMiddleware(
        model=FakeListChatModel(responses=["unused"]), keep=("tokens", 6000)
    )
    assert middleware.name == "SummarizationMiddleware"
    messages = [
        HumanMessage(content="Original requirement"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "read_file", "args": {}, "id": "a"},
                {"name": "read_file", "args": {}, "id": "b"},
            ],
        ),
        ToolMessage(content="large evidence " * 30000, tool_call_id="a"),
    ]
    assert middleware._determine_cutoff_index(messages) == 1


@pytest.mark.integration
@pytest.mark.parametrize("failure_stage", ["map", "reduce"])
async def test_large_parallel_tool_results_resume_private_map_progress_across_postgres_workers(
    tmp_path, postgres_url, failure_stage
):
    kr, work = assignment()
    work = work.model_copy(update={"task": "ORIGINAL_REQUIREMENT: Preserve all three source facts"})
    turns = 0
    healthy = False
    successful_summaries = []
    summary_attempts = []
    failed_index = None

    def script(body, requests):
        nonlocal turns
        progress = progress_payload(body)
        if progress is not None:
            successful_summaries.append(progress)
            return evidence_report(progress)
        if body.get("response_format"):
            return extracted_deliverable(body)
        turns += 1
        if turns == 1:
            return {
                "tool_calls": [
                    tool_call("read_file", {"path": f"source-{index}.txt"}, f"source-{index}")
                    for index in range(3)
                ]
            }
        if turns == 2:
            assert "ORIGINAL_REQUIREMENT" in str(body["messages"])
            assert all(f"EVIDENCE_{index}" in str(body["messages"]) for index in range(3))
            return {
                "tool_calls": [
                    tool_call(
                        "write_file", {"path": "result.txt", "content": "Verified all sources"}
                    )
                ]
            }
        return {"content": "Completed the verified output using all three recorded source facts."}

    async with services_with_provider(tmp_path, script, limits=UNLIMITED) as (
        provider,
        _,
        _,
        requests,
        workspace,
    ):
        for index in range(3):
            (workspace / f"source-{index}.txt").write_text(
                f"EVIDENCE_{index} " + "🧭 research reference " * 2600
            )
        provider.model.async_client.max_retries = 0
        transport = provider.model.async_client._client._transport
        normal_handler = transport.handler

        def handler(request):
            nonlocal failed_index
            body = json.loads(request.content)
            progress = progress_payload(body)
            if progress is not None:
                summary_attempts.append(progress)
                fail_map = failure_stage == "map" and len(successful_summaries) == 2
                fail_reduce = (
                    failure_stage == "reduce"
                    and progress.startswith("Recorded facts:")
                    and sum(value.startswith("Recorded facts:") for value in successful_summaries)
                    == 1
                )
                if not healthy and (fail_map or fail_reduce):
                    failed_index = len(successful_summaries)
                    requests.append(body)
                    return httpx.Response(401, json={"error": {"message": "isolated map fault"}})
            return normal_handler(request)

        transport.handler = handler
        settings = Settings(
            _env_file=None,
            openai_api_key="fixture-key",
            database_url=postgres_url,
            data_dir=provider.settings.data_dir,
        )
        await migrate(settings)
        instances = []
        storage = PostgresStorage(postgres_url)
        await storage.open()
        try:
            run = await storage.create_run(
                RunCreate(
                    user_request="ORIGINAL_REQUIREMENT: Preserve three independent sources",
                    workspace_path=str(workspace),
                    limits=UNLIMITED,
                ).model_dump(mode="json")
            )
            async with AsyncPostgresSaver.from_conn_string(postgres_url) as saver:
                assert await Worker(
                    settings,
                    storage,
                    checkpointer=saver,
                    services_factory=service_factory(provider.model, instances),
                    graph_factory=execute_graph(kr, work),
                ).run_once()
                waiting = await storage.get_run(run["run_id"])
                assert waiting["status"] == "queued" and waiting["review"] is None
                assert waiting["tool_calls"] == 3 and turns == 1
                assert waiting["model_calls"] == len(requests) == len(successful_summaries) + 2
                private = await private_snapshots(storage, saver, run["run_id"])
                assert len(private) == 1
                original = get_buffer_string(private[0].checkpoint["channel_values"]["messages"])
                summary = await private_snapshots(storage, saver, run["run_id"], summaries=True)
                assert len(summary) == 1
                summary_thread = summary[0].config["configurable"]["thread_id"]
                values = summary[0].checkpoint["channel_values"]
                assert values["stage"] == failure_stage and values["offset"] == 2
                assert len(values["partials"]) == (2 if failure_stage == "map" else 1)
                if failure_stage == "map":
                    assert "".join(values["chunks"]) == original
                await storage.update_run(run["run_id"], next_attempt_at="2020-01-01T00:00:00+00:00")
        finally:
            await storage.close()
        healthy = True
        reopened = PostgresStorage(postgres_url)
        await reopened.open()
        try:
            async with AsyncPostgresSaver.from_conn_string(postgres_url) as saver:
                assert await Worker(
                    settings,
                    reopened,
                    checkpointer=saver,
                    services_factory=service_factory(provider.model, instances),
                    graph_factory=execute_graph(kr, work),
                ).run_once()
                current = await reopened.get_run(run["run_id"])
                assert current["status"] == "succeeded" and current["review"] is None
                assert current["model_calls"] == len(requests)
                recorded = await operations(reopened, run["run_id"])
                assert current["tool_calls"] == len(recorded) == 4
                assert sum("content" in item["request"] for item in recorded) == 1
                summaries = await private_snapshots(reopened, saver, run["run_id"], summaries=True)
                completed = next(
                    item
                    for item in summaries
                    if item.config["configurable"]["thread_id"] == summary_thread
                )
                assert completed.checkpoint["channel_values"]["report"]
                outer = await saver.aget_tuple(runtime_config(run["run_id"]))
                assert "messages" not in outer.checkpoint["channel_values"]
        finally:
            await reopened.close()
        chunks = split_progress(original)
        assert "".join(successful_summaries[: len(chunks)]) == original
        assert len(successful_summaries) == len(chunks) * 2 - 1
        # Original chunks may have identical repeated content. Compare the full
        # ordered requests: only the failed map or reduction is requested twice.
        assert failed_index is not None
        assert summary_attempts == [
            *successful_summaries[:failed_index],
            successful_summaries[failed_index],
            *successful_summaries[failed_index:],
        ]
        assert all(len(value.encode("utf-8")) <= SUMMARY_REDUCE_BYTES for value in summary_attempts)
        assert all(
            len(value.encode("utf-8")) <= SUMMARY_INPUT_BYTES
            for value in successful_summaries[: len(chunks)]
        )
        assert len(instances) == 2 and turns == 3
        # No giant newest tool block reaches an ordinary agent model request.
        assert (
            max(
                len(json.dumps(request["messages"], ensure_ascii=False).encode("utf-8"))
                for request in requests
                if not request.get("response_format")
            )
            < SUMMARY_INPUT_BYTES
        )
        assert (workspace / "result.txt").read_text() == "Verified all sources"


@pytest.mark.parametrize("actor", ["planner", "engineering_head"])
async def test_planning_immutable_context_remains_authoritative_after_lossy_full_compaction(
    tmp_path, monkeypatch, actor
):
    kr, work = assignment()
    mission = "PINNED_MISSION: ship the exact requested output with ORIGINAL_USER_CRITERION."
    constitution = Constitution(
        mission_statement="PINNED_CONSTITUTION: preserve traceable 🧭 evidence",
        prohibited_actions=("PINNED_PROHIBITION: never fabricate a source",),
        compliance_rules=("PINNED_COMPLIANCE: preserve source attribution",),
    )
    kr = kr.model_copy(
        update={
            "description": "PINNED_KR: implement and verify the agreed result",
            "acceptance_criteria": ("PINNED_KR_CRITERION: execute the exact verification",),
        }
    )
    work = work.model_copy(
        update={"task": kr.description, "acceptance_criteria": kr.acceptance_criteria}
    )
    answer = (
        StrategicPlan(
            objectives=(
                StrategicObjective(objective_id="goal", title="Original goal", key_results=(kr,)),
            )
        )
        if actor == "planner"
        else TacticalPlan(work_packages=(work,))
    )
    turns = 0
    summaries = 0

    def script(body, requests):
        nonlocal turns, summaries
        if progress_payload(body) is not None:
            summaries += 1
            # Deliberately lossy: authoritative requirements must not rely on this report.
            return {
                "content": '{"report":"Saved capability findings; continue the assigned work."}'
            }
        turns += 1
        system = body["messages"][0]["content"]
        assert mission in system
        assert constitution.mission_statement in system
        assert constitution.prohibited_actions[0] in system
        assert constitution.compliance_rules[0] in system
        if actor == "engineering_head":
            assert kr.description in system and kr.acceptance_criteria[0] in system
        if turns == 1:
            return {
                "tool_calls": [
                    tool_call(
                        "consult_tools_rd",
                        {"requirement": f"Research capability {index}", "mode": "research"},
                        f"capability-{index}",
                    )
                    for index in range(6)
                ]
            }
        assert summaries > 0
        retained = str(body["messages"][1:])
        assert "Saved capability findings" in retained
        assert "PINNED_" not in retained and "ORIGINAL_USER_CRITERION" not in retained
        return {"content": answer.model_dump_json()}

    async with services_with_provider(tmp_path, script, limits=UNLIMITED) as (
        services,
        storage,
        run,
        requests,
        _,
    ):
        services.run["user_request"] = mission
        await storage.update_run(run["run_id"], user_request=mission)

        async def capability(*args, **kwargs):
            return {"report": "Capability reference with recorded evidence. " * 2500}

        monkeypatch.setattr(services, "consult_tools_rd", capability)
        payload = {
            "constitution": constitution.model_dump(),
            **({"user_request": mission} if actor == "planner" else {"kr": kr.model_dump()}),
        }
        result = await services.planning_agent(
            type(answer),
            "Preserve immutable requirements and return the assigned contract.",
            payload,
            actor=actor,
            constitution=constitution,
            kr=None if actor == "planner" else kr,
        )
        assert result == answer and turns == 2 and summaries > 0
        current = await storage.get_run(run["run_id"])
        assert current["model_calls"] == len(requests) == turns + summaries
