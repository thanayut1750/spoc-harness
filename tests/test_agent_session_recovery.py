"""Real private LangChain sessions retain verified effects across Postgres restarts."""

import asyncio
import json

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError
from test_agent_services import assignment, services_with_provider, tool_call
from test_dynamic_services import extracted_deliverable
from typing_extensions import TypedDict

from org_harness.agent_services import AgentServices
from org_harness.agent_sessions import ProgressSummary, session_middleware
from org_harness.config import Settings
from org_harness.models import Constitution, EscalationSignal, RunCreate
from org_harness.runtime import runtime_config
from org_harness.storage import PostgresStorage
from org_harness.worker import Worker, migrate

UNLIMITED = {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None}


class ExecutiveState(TypedDict, total=False):
    run_id: str
    status: str
    report: str


def execute_graph(kr, work):
    def factory(services, *, checkpointer=None, store=None):
        assert services.agent_checkpointer is checkpointer

        async def execute(state):
            result = await services.execute(work, kr, Constitution(), [], "", 0)
            return {"status": "completed", "report": result.summary}

        return (
            StateGraph(ExecutiveState)
            .add_node("execute", execute)
            .add_edge(START, "execute")
            .add_edge("execute", END)
            .compile(checkpointer=checkpointer)
        )

    return factory


async def private_snapshots(storage, saver, run_id, *, summaries=False):
    async with storage.pool.connection() as connection:
        rows = await (
            await connection.execute(
                "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE %s",
                (f"{run_id}:private:%",),
            )
        ).fetchall()
    rows = [row for row in rows if (":private:summary:" in row["thread_id"]) is summaries]
    return [
        await saver.aget_tuple({"configurable": {"thread_id": row["thread_id"]}}) for row in rows
    ]


async def operations(storage, run_id):
    async with storage.pool.connection() as connection:
        rows = await (
            await connection.execute(
                "SELECT data FROM harness_operations WHERE run_id=%s", (run_id,)
            )
        ).fetchall()
    return [row["data"] for row in rows]


def service_factory(model, instances):
    def factory(settings, storage, current):
        services = AgentServices(settings, storage, current)
        services.model_for = lambda actor=None: model
        instances.append(services)
        return services

    return factory


@pytest.mark.integration
async def test_postgres_private_agent_resumes_three_fresh_workers_without_replaying_effects(
    tmp_path, postgres_url
):
    kr, work = assignment()
    turns = 0
    summaries = 0
    summarized_progress = []
    output = "VERIFIED durable reference line\n" * 140

    def script(body, requests):
        nonlocal turns, summaries
        if body.get("response_format"):
            if "Compact private task progress" in body["messages"][0]["content"]:
                summaries += 1
                summarized_progress.append(
                    json.loads(body["messages"][1]["content"])["private_progress"]
                )
                return {
                    "content": json.dumps(
                        {
                            "report": "VERIFIED output.txt was written once. Continue the remaining recorded verification reads, then submit its artifact ID."
                        }
                    )
                }
            return extracted_deliverable(body)
        turns += 1
        if turns == 71:
            return {"content": "Completed the verified durable output."}
        return {
            "tool_calls": [
                tool_call(
                    "write_file" if turns == 1 else "read_file",
                    {"path": "output.txt", **({"content": output} if turns == 1 else {})},
                    f"step-{turns}",
                )
            ]
        }

    async with services_with_provider(tmp_path, script, limits=UNLIMITED) as (
        provider,
        _,
        _,
        requests,
        workspace,
    ):
        settings = Settings(
            _env_file=None,
            openai_api_key="fixture-key",
            database_url=postgres_url,
            data_dir=provider.settings.data_dir,
        )
        await migrate(settings)
        initial = PostgresStorage(postgres_url)
        await initial.open()
        try:
            run = await initial.create_run(
                RunCreate(
                    user_request="Preserve verified progress",
                    workspace_path=str(workspace),
                    limits=UNLIMITED,
                ).model_dump(mode="json")
            )
        finally:
            await initial.close()
        instances = []
        previous_tools = 0
        for chunk in range(3):
            storage = PostgresStorage(postgres_url)
            await storage.open()
            try:
                async with AsyncPostgresSaver.from_conn_string(postgres_url) as saver:
                    assert await Worker(
                        settings,
                        storage,
                        checkpointer=saver,
                        services_factory=service_factory(provider.model, instances),
                        graph_factory=execute_graph(kr, work),
                    ).run_once()
                    current = await storage.get_run(run["run_id"])
                    assert current["review"] is None
                    assert current["model_calls"] == len(requests)
                    assert current["tool_calls"] > previous_tools
                    previous_tools = current["tool_calls"]
                    outer = await saver.aget_tuple(runtime_config(run["run_id"]))
                    assert "messages" not in outer.checkpoint["channel_values"]
                    private = await private_snapshots(storage, saver, run["run_id"])
                    assert len(private) == 1
                    assert private[0].checkpoint["channel_values"]["messages"]
                    recorded = await operations(storage, run["run_id"])
                    assert len(recorded) == current["tool_calls"]
                    assert all(item["status"] == "done" for item in recorded)
                    writes = [item for item in recorded if "content" in item["request"]]
                    assert len(writes) == 1
                    if chunk < 2:
                        assert current["status"] == "queued"
                        assert current["autonomous_failures"] == 0
            finally:
                await storage.close()
        assert len(instances) == 3
        assert current["status"] == "succeeded"
        assert current["tool_calls"] == 70
        assert turns == 71 and summaries > 0
        assert f"Human: {work.task}" in summarized_progress[0]
        assert "VERIFIED durable reference line" in summarized_progress[0]
        # Large tool results trigger compaction before the 60-message threshold.
        assert (
            max(
                len(request["messages"])
                for request in requests
                if not request.get("response_format")
            )
            < 60
        )
        assert not any(
            "Previous conversation was too long to summarize." in str(request["messages"])
            for request in requests
        )
        assert len(requests) == turns + summaries + 1
        assert (workspace / "output.txt").read_text() == output
        assert any(
            "VERIFIED output.txt" in str(message.get("content"))
            for request in requests
            if not request.get("response_format")
            for message in request["messages"]
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "fault", ["invalid_summary", "whitespace_summary", "authentication", "transient"]
)
async def test_failed_private_compaction_keeps_same_postgres_history_until_provider_recovers(
    tmp_path, postgres_url, fault
):
    kr, work = assignment()
    healthy = False
    turns = 0
    summary_attempts = 0
    output = "VERIFIED ORIGINAL ARTIFACT - unchanged requirement\n" * 50

    def script(body, requests):
        nonlocal turns, summary_attempts
        if body.get("response_format"):
            if "Compact private task progress" in body["messages"][0]["content"]:
                summary_attempts += 1
                return {
                    "content": json.dumps(
                        {
                            "report": "VERIFIED output.txt exists. Do not repeat its completed write. Finish remaining reads and submit the saved artifact."
                        }
                    )
                    if healthy
                    else json.dumps({"report": " \t\n " if fault == "whitespace_summary" else ""})
                }
            return extracted_deliverable(body)
        turns += 1
        if turns == 41:
            return {"content": "The original output is verified and complete."}
        return {
            "tool_calls": [
                tool_call(
                    "write_file" if turns == 1 else "read_file",
                    {"path": "output.txt", **({"content": output} if turns == 1 else {})},
                    f"operation-{turns}",
                )
            ]
        }

    async with services_with_provider(tmp_path, script, limits=UNLIMITED) as (
        provider,
        _,
        _,
        requests,
        workspace,
    ):
        # Production ZaiChatModel disables SDK retries; policy owns every budgeted retry.
        provider.model.async_client.max_retries = 0
        if fault in {"authentication", "transient"}:
            transport = provider.model.async_client._client._transport
            normal_handler = transport.handler

            def handler(request):
                nonlocal summary_attempts
                body = json.loads(request.content)
                if (
                    not healthy
                    and body.get("response_format")
                    and "Compact private task progress" in body["messages"][0]["content"]
                ):
                    summary_attempts += 1
                    requests.append(body)
                    return httpx.Response(
                        401 if fault == "authentication" else 503,
                        json={
                            "error": {
                                "message": "isolated summary provider fault",
                                "type": "test_fault",
                            }
                        },
                    )
                return normal_handler(request)

            transport.handler = handler
        settings = Settings(
            _env_file=None,
            openai_api_key="fixture-key",
            database_url=postgres_url,
            data_dir=provider.settings.data_dir,
        )
        await migrate(settings)
        storage = PostgresStorage(postgres_url)
        await storage.open()
        instances = []
        try:
            run = await storage.create_run(
                RunCreate(
                    user_request="Keep exact verified output and continue",
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
                assert waiting["autonomous_failures"] == 1
                assert waiting["next_attempt_at"]
                assert waiting["continuation"]["reason"] == (
                    "Private progress compaction temporarily unavailable; saved history preserved"
                )
                assert summary_attempts > 0 and 1 < turns < 32
                old_private = await private_snapshots(storage, saver, run["run_id"])
                assert len(old_private) == 1
                old_history = old_private[0].checkpoint["channel_values"]["messages"]
                assert any(
                    "VERIFIED ORIGINAL ARTIFACT" in str(message.content) for message in old_history
                )
                assert not any(
                    "VERIFIED output.txt exists" in str(message.content) for message in old_history
                )
                original_operations = await operations(storage, run["run_id"])
                original_ids = {item["operation_id"] for item in original_operations}
                assert len(original_ids) == waiting["tool_calls"]
                assert waiting["model_calls"] == len(requests)
                # Make the persisted cooldown due without sleeping or modifying any live run.
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
                new_private = await private_snapshots(reopened, saver, run["run_id"])
                assert len(new_private) == 1
                assert (
                    new_private[0].config["configurable"]["thread_id"]
                    == old_private[0].config["configurable"]["thread_id"]
                )
                assert current["model_calls"] == len(requests)
                recorded = await operations(reopened, run["run_id"])
                assert current["tool_calls"] == len(recorded) == 40
                assert original_ids <= {item["operation_id"] for item in recorded}
                assert sum("content" in item["request"] for item in recorded) == 1
                assert turns == 41
                outer = await saver.aget_tuple(runtime_config(run["run_id"]))
                assert "messages" not in outer.checkpoint["channel_values"]
        finally:
            await reopened.close()
        assert (workspace / "output.txt").read_text() == output


def test_private_progress_rejects_whitespace_without_normalizing_real_reports():
    for whitespace in (" ", "\t\r\n", "\u2003\u00a0"):
        with pytest.raises(ValidationError):
            ProgressSummary(report=whitespace)
    original = "\n Verified evidence and unresolved work. \t"
    assert ProgressSummary(report=original).report == original


@pytest.mark.parametrize("fault", ["cancel", "cancelled", "suspended", "policy", "unexpected"])
async def test_private_compaction_does_not_convert_cancellation_policy_or_programming_errors(
    tmp_path, fault
):
    error = {
        "cancel": asyncio.CancelledError(),
        "cancelled": EscalationSignal("cancelled", "Run was cancelled"),
        "suspended": EscalationSignal("suspended", "Execution suspended for constitution review"),
        "policy": EscalationSignal("constitution_violation", "original policy blocker"),
        "unexpected": RuntimeError("unexpected programming error"),
    }[fault]

    async with services_with_provider(tmp_path, lambda *_: {}, limits=UNLIMITED) as (
        services,
        *_rest,
    ):

        async def failed_summary(*args, **kwargs):
            raise error

        services.structured = failed_summary
        summarizer = session_middleware(services, "backend_coder")[1].summarizer
        with pytest.raises(type(error)) as raised:
            await summarizer.ainvoke([HumanMessage(content="Private progress")])
        assert raised.value is error
