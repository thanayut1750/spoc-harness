"""Real private agent checkpoints survive work chunks and process lifetimes."""

import json

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from test_agent_services import assignment, services_with_provider, tool_call
from test_dynamic_services import extracted_deliverable
from typing_extensions import TypedDict

from org_harness.agent_services import AgentServices
from org_harness.models import Constitution
from org_harness.runtime import runtime_config
from org_harness.worker import Worker

UNLIMITED = {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None}


async def test_private_agent_resumes_across_fresh_workers_and_compacts_without_replaying_tools(
    tmp_path,
):
    kr, work = assignment()
    turns = 0
    summary_calls = 0
    verified_output = "Verified durable output\n" * 100

    def script(body, requests):
        nonlocal turns, summary_calls
        if body.get("response_format"):
            if "private_progress" in json.loads(body["messages"][-1]["content"]):
                summary_calls += 1
                return {
                    "content": json.dumps(
                        {
                            "report": "Saved output.txt contains verified work. Completed file reads are journaled. Continue verification, then submit artifact IDs."
                        }
                    )
                }
            return extracted_deliverable(body)
        turns += 1
        if turns == 71:
            return {"content": "The durable output and verification are complete."}
        return {
            "tool_calls": [
                tool_call(
                    "write_file" if turns == 1 else "read_file",
                    {
                        "path": "output.txt",
                        **({"content": verified_output} if turns == 1 else {}),
                    },
                    f"operation-{turns}",
                )
            ]
        }

    class State(TypedDict, total=False):
        run_id: str
        status: str
        report: str

    def graph_factory(services, *, checkpointer=None, store=None):
        async def execute(state):
            result = await services.execute(work, kr, Constitution(), [], "", 0)
            return {"status": "completed", "report": result.summary}

        return (
            StateGraph(State)
            .add_node("execute", execute)
            .add_edge(START, "execute")
            .add_edge("execute", END)
            .compile(checkpointer=checkpointer)
        )

    async with services_with_provider(tmp_path, script, limits=UNLIMITED) as (
        provider,
        storage,
        run,
        requests,
        workspace,
    ):
        await storage.update_run(run["run_id"], constitution=Constitution().model_dump(mode="json"))
        saver = InMemorySaver()
        service_instances = []

        def factory(settings, storage, current):
            services = AgentServices(settings, storage, current)
            services.model_for = lambda actor=None: provider.model
            service_instances.append(services)
            return services

        for chunk in range(4):
            worker = Worker(
                provider.settings,
                storage,
                services_factory=factory,
                graph_factory=graph_factory,
                checkpointer=saver,
            )
            assert await worker.run_once()
            current = await storage.get_run(run["run_id"])
            assert current["review"] is None
            outer = await saver.aget_tuple(runtime_config(run["run_id"]))
            assert "messages" not in outer.checkpoint["channel_values"]
            if chunk == 0:
                assert current["status"] == "queued"
                assert current["tool_calls"] == 32
                assert current["autonomous_failures"] == 0
            if current["status"] == "succeeded":
                break
        assert current["status"] == "succeeded" and chunk == 2
        assert len(service_instances) == 3
        assert summary_calls >= 1
        assert current["tool_calls"] == 70 and len(storage.operations) == 70
        assert (workspace / "output.txt").read_text() == verified_output
        writes = [
            operation
            for operation in storage.operations.values()
            if operation["request"].get("path") == "output.txt"
            and "content" in operation["request"]
        ]
        assert len(writes) == 1 and writes[0]["status"] == "done"
        assert current["model_calls"] == len(requests) == turns + summary_calls + 1
        # Each provider request is bounded after old messages are compacted.
        assert (
            max(
                len(request["messages"])
                for request in requests
                if not request.get("response_format")
            )
            < 65
        )
