"""Unlimited model budgets reach real agents while independent controls remain active."""

import sys

import pytest
from langchain.agents.middleware import ModelCallLimitMiddleware
from test_agent_services import assignment, services_with_provider, tool_call
from test_exa_agent_tools import extracted_deliverable

from org_harness import agent_services
from org_harness.models import (
    Constitution,
    EngineeringSpecialistSpec,
    EscalationSignal,
    StrategicObjective,
    StrategicPlan,
    TacticalPlan,
    worker_agent_id,
)


def record_real_agents(monkeypatch):
    original = agent_services.create_agent
    created = []

    def create(*args, **kwargs):
        compiled = original(*args, **kwargs)
        invoke = compiled.ainvoke
        record = {"middleware": kwargs["middleware"], "name": kwargs["name"], "configs": []}
        created.append(record)

        async def observed(inputs, config=None, **options):
            record["configs"].append(config)
            return await invoke(inputs, config, **options)

        monkeypatch.setattr(compiled, "ainvoke", observed)
        return compiled

    monkeypatch.setattr(agent_services, "create_agent", create)
    return created


def assert_unlimited_graphs(created):
    assert created
    for record in created:
        assert not any(isinstance(item, ModelCallLimitMiddleware) for item in record["middleware"])
        assert record["configs"] and all(
            config["recursion_limit"] == sys.maxsize for config in record["configs"]
        )


@pytest.mark.parametrize("actor", ["fixed", "specialist", "tools_rd_lead"])
async def test_unlimited_workers_and_rd_exceed_old_turn_limits(tmp_path, monkeypatch, actor):
    kr, work = assignment()
    if actor == "specialist":
        work = work.model_copy(
            update={
                "specialist": EngineeringSpecialistSpec(
                    name="Long-running verification specialist",
                    instructions="Save the output and verify it using recorded file reads.",
                    tools=("write_file", "read_file"),
                )
            }
        )
    turns = 351 if actor == "fixed" else 101

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        turn = len(requests)
        if turn == turns:
            return {"content": "Completed the saved output and its repeated verification."}
        return {
            "tool_calls": [
                tool_call(
                    "write_file" if turn == 1 else "read_file",
                    {"path": "output.txt", **({"content": "Verified output"} if turn == 1 else {})},
                    f"step-{turn}",
                )
            ]
        }

    created = record_real_agents(monkeypatch)
    async with services_with_provider(
        tmp_path,
        script,
        limits={"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": 500},
    ) as (services, storage, run, requests, workspace):
        if actor == "tools_rd_lead":
            parent = services._planning_host("engineering_head", kr)
            result = await services.consult_tools_rd(
                "engineering_head",
                "Investigate the saved output",
                Constitution(),
                parent,
                "long-investigation",
                kr,
                mode="research",
            )
            assert result["report"] and result["report_artifact_id"] in result["artifact_ids"]
            assert not (workspace / "output.txt").exists()
        else:
            result = await services.execute(work, kr, Constitution(), [], "", 0)
            assert result.worker_role == worker_agent_id(run["run_id"], work)
            assert not result.fallback and result.artifact_ids
            assert (workspace / "output.txt").read_text() == "Verified output"
        assert len(requests) == turns + 1  # Typed extraction remains globally metered.
        assert sum(not body.get("response_format") for body in requests) == turns
        saved = await storage.get_run(run["run_id"])
        assert saved["model_calls"] == turns + 1
        assert saved["tool_calls"] == turns - 1 + (actor == "tools_rd_lead")
        output = next(
            item
            for item in await storage.list_artifacts(run["run_id"])
            if item["name"] == "output.txt"
        )
        _, content = await services.artifacts.read(output["artifact_id"], limit=None)
        assert content == "Verified output"
        assert len(created) == 1
        assert created[0]["name"] == (
            "tools_rd_lead" if actor == "tools_rd_lead" else worker_agent_id(run["run_id"], work)
        )
        # Every actor exceeds the old 100-turn budget; the fixed-worker case
        # also traverses over 1,000 actual model/after-model/tool graph steps.
        assert_unlimited_graphs(created)


@pytest.mark.parametrize("caller", ["planner", "engineering_head"])
async def test_unlimited_planning_agents_complete_more_than_a_hundred_turns(
    tmp_path, monkeypatch, caller
):
    kr, work = assignment()
    strategic = StrategicPlan(
        objectives=(
            StrategicObjective(objective_id="objective", title="Output", key_results=(kr,)),
        )
    )

    def script(body, requests):
        assert not body.get("response_format")
        assert {item["function"]["name"] for item in body["tools"]} == {
            "consult_tools_rd",
            "run_mission_tool",
        }
        if len(requests) == 101:
            return {
                "content": strategic.model_dump_json()
                if caller == "planner"
                else TacticalPlan(work_packages=(work,)).model_dump_json()
            }
        # A known tool input failure is a real tool turn; it must not be
        # confused with an uncaught execution failure or spawn extra agents.
        return {
            "tool_calls": [
                tool_call(
                    "run_mission_tool",
                    {"tool_id": "missing-tool", "arguments": {}},
                    f"capability-check-{len(requests)}",
                )
            ]
        }

    created = record_real_agents(monkeypatch)
    async with services_with_provider(
        tmp_path, script, limits={"max_model_calls": None, "worker_model_calls": None}
    ) as (services, storage, run, requests, _):
        if caller == "planner":
            assert await services.plan("Build the requested output", Constitution()) == list(
                strategic.objectives
            )
        else:
            packages = await services.plan_work(kr, Constitution(), [], "")
            assert len(packages) == 1 and packages[0].role == work.role
        assert len(requests) == 101 and len(created) == 1 and created[0]["name"] == caller
        assert_unlimited_graphs(created)
        saved = await storage.get_run(run["run_id"])
        assert (saved["model_calls"], saved["tool_calls"]) == (101, 100)
        assert all(item["status"] == "done" for item in storage.operations.values())


@pytest.mark.parametrize("finite_budget", ["worker", "mission"])
async def test_one_unlimited_budget_does_not_disable_the_other_finite_budget(
    tmp_path, finite_budget
):
    kr, work = assignment()

    def script(body, requests):
        if finite_budget == "mission" and len(requests) == 3:
            return {"content": "The saved output is ready for extraction."}
        assert not body.get("response_format")
        return {
            "tool_calls": [
                tool_call(
                    "write_file" if len(requests) == 1 else "read_file",
                    {
                        "path": "output.txt",
                        **({"content": "Preserved output"} if len(requests) == 1 else {}),
                    },
                    f"turn-{len(requests)}",
                )
            ]
        }

    async with services_with_provider(
        tmp_path,
        script,
        limits={
            "max_model_calls": 3 if finite_budget == "mission" else None,
            "worker_model_calls": 3 if finite_budget == "worker" else None,
        },
    ) as (services, storage, run, requests, workspace):
        with pytest.raises(EscalationSignal) as error:
            await services.execute(work, kr, Constitution(), [], "", 0)
        assert error.value.kind == "limit_exceeded"
        assert len(requests) == 3 and (workspace / "output.txt").read_text() == "Preserved output"
        saved = await storage.get_run(run["run_id"])
        assert saved["model_calls"] == 3
        assert saved["tool_calls"] == (2 if finite_budget == "mission" else 3)
        artifacts = await storage.list_artifacts(run["run_id"])
        assert any(item["kind"] == "source" for item in artifacts)
        assert not any(item["kind"] == "deliverable" for item in artifacts)


async def test_unlimited_model_budgets_preserve_the_independent_tool_cap(tmp_path):
    kr, work = assignment()

    def script(body, requests):
        return {
            "tool_calls": [tool_call("read_file", {"path": "input.txt"}, f"read-{len(requests)}")]
        }

    async with services_with_provider(
        tmp_path,
        script,
        limits={"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": 2},
    ) as (services, storage, run, requests, workspace):
        (workspace / "input.txt").write_text("Existing input")
        with pytest.raises(EscalationSignal) as error:
            await services.execute(work, kr, Constitution(), [], "", 0)
        assert error.value.kind == "limit_exceeded" and len(requests) == 3
        saved = await storage.get_run(run["run_id"])
        assert (saved["model_calls"], saved["tool_calls"]) == (3, 2)


async def test_unlimited_model_budgets_still_honor_cancellation_between_turns(
    tmp_path, monkeypatch
):
    kr, work = assignment()

    def script(body, requests):
        return {
            "tool_calls": [
                tool_call("write_file", {"path": "partial.txt", "content": "Saved partial work"})
            ]
        }

    async with services_with_provider(
        tmp_path, script, limits={"max_model_calls": None, "worker_model_calls": None}
    ) as (services, storage, run, requests, workspace):
        emit = services.emit

        async def cancel_after_write(agent_id, activity, summary, **data):
            await emit(agent_id, activity, summary, **data)
            if activity == "writing":
                await storage.command(run["run_id"], "cancel", {})

        monkeypatch.setattr(services, "emit", cancel_after_write)
        with pytest.raises(EscalationSignal) as error:
            await services.execute(work, kr, Constitution(), [], "", 0)
        assert error.value.kind == "cancelled" and len(requests) == 1
        assert (workspace / "partial.txt").read_text() == "Saved partial work"
        saved = await storage.get_run(run["run_id"])
        assert (saved["model_calls"], saved["tool_calls"]) == (1, 1)
        assert not any(
            item["kind"] == "deliverable" for item in await storage.list_artifacts(run["run_id"])
        )
