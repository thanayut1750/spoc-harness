"""Dependency-aware specialist waves retain immutable results across retries."""

import asyncio
from collections import Counter

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import ValidationError
from test_runtime import Services, evaluation, kr

from org_harness.autonomy import AutonomousCheckpointYield
from org_harness.models import (
    Constitution,
    Deliverable,
    EscalationSignal,
    RunLimits,
    TacticalPlan,
    TaskSpecialistSpec,
    WorkPackage,
    normalized_work_dependencies,
    worker_agent_id,
)
from org_harness.runtime import build_graph, initial_state, runtime_config

RUN = "async-runtime"


def package(name, dependencies=(), *, mode="async", critical=True):
    return WorkPackage(
        work_package_id=name,
        kr_id="build",
        role="backend_coder",
        task=f"Produce {name}",
        acceptance_criteria=(f"Accept {name}",),
        critical=critical,
        specialist=TaskSpecialistSpec(
            name=f"{name} specialist", instructions=f"Produce only {name}"
        ),
        execution_mode=mode,
        depends_on=dependencies,
    )


class AsyncServices(Services):
    def __init__(self, packages, *, world=None):
        super().__init__(kr("build", "engineering"))
        self.proposed = packages
        self.world = (
            world
            if world is not None
            else {"counts": Counter(), "order": [], "active": 0, "max_active": 0}
        )
        self.started = {work.work_package_id: asyncio.Event() for work in packages}
        self.completed = {work.work_package_id: asyncio.Event() for work in packages}
        self.before_execute = None
        self.reject = None
        self.optional = set()

    async def plan_work(self, *args):
        return self.proposed

    async def execute(self, work, key_result, constitution, inputs, feedback, epoch):
        self.executions.append((work, inputs, feedback, epoch))
        self.world["counts"][work.work_package_id] += 1
        self.world["active"] += 1
        self.world["max_active"] = max(self.world["max_active"], self.world["active"])
        self.started[work.work_package_id].set()
        try:
            if self.before_execute:
                await self.before_execute(work)
            await asyncio.sleep(0)
            self.world["order"].append(work.work_package_id)
            self.completed[work.work_package_id].set()
            return Deliverable(
                kr_id=key_result.kr_id,
                department=key_result.target_department,
                worker_role=worker_agent_id(RUN, work),
                summary=f"{work.work_package_id} output attempt {work.execution_attempt}",
                artifact_ids=(f"{work.work_package_id}-a{work.execution_attempt}",),
                evidence=("Recorded check exited successfully",),
                confidence_score=0 if work.work_package_id in self.optional else 1,
                fallback=work.work_package_id in self.optional,
            )
        finally:
            self.world["active"] -= 1

    async def evaluate(self, deliverable, criteria, constitution):
        self.evaluations.append((deliverable, criteria))
        passed = not (self.reject and self.reject(deliverable, criteria))
        return evaluation(
            criteria,
            passed_kr_criteria=passed,
            score=1 if passed else 0,
            criterion_results=dict.fromkeys(criteria, passed),
            feedback="Accepted" if passed else "Repair this package",
        )


async def run(services, saver=None):
    graph = build_graph(services, checkpointer=saver or InMemorySaver())
    async with asyncio.timeout(8):
        result = await graph.ainvoke(
            initial_state(RUN, "Build requested output", Constitution()), runtime_config(RUN)
        )
    return graph, result


@pytest.mark.parametrize(
    "change",
    ["unknown", "self", "duplicate", "cycle", "duplicate_id", "async_implicit", "async_unnamed"],
)
def test_tactical_dependency_contract_rejects_invalid_graphs(change):
    values = [package("first").model_dump(), package("second", ("first",)).model_dump()]
    if change == "unknown":
        values[1]["depends_on"] = ["missing"]
    elif change == "self":
        values[1]["depends_on"] = ["second"]
    elif change == "duplicate":
        values[1]["depends_on"] = ["first", "first"]
    elif change == "cycle":
        values[0]["depends_on"] = ["second"]
    elif change == "duplicate_id":
        values[1]["work_package_id"] = "first"
    elif change == "async_implicit":
        values[0]["depends_on"] = None
    else:
        values[0]["specialist"] = None
    with pytest.raises(ValidationError):
        TacticalPlan.model_validate({"work_packages": values})


async def test_forged_model_copy_cannot_dispatch_an_invalid_async_assignment():
    work = package("first").model_copy(update={"specialist": None})
    services = AsyncServices([work])
    _, result = await run(services)
    assert result["status"] == "awaiting_review" and not services.executions


async def test_independent_tasks_overlap_and_join_in_plan_order_with_only_declared_inputs():
    services = AsyncServices(
        [
            package("first"),
            package("second"),
            package("third", ("first",), mode="sync"),
            package("fourth", ("first", "second"), mode="sync"),
        ]
    )

    async def reverse_finish(work):
        if work.work_package_id == "first":
            await services.completed["second"].wait()

    services.before_execute = reverse_finish
    _, result = await run(services)
    assert result["status"] == "completed" and services.world["max_active"] == 2
    assert services.world["order"][:2] == ["second", "first"]
    inputs = {
        work.work_package_id: [item.artifact_ids[0] for item in deps]
        for work, deps, *_ in services.executions
    }
    assert inputs == {
        "first": [],
        "second": [],
        "third": ["first-a0"],
        "fourth": ["first-a0", "second-a0"],
    }
    combined = next(item for item, _ in services.evaluations if item.worker_role.endswith("_head"))
    assert combined.artifact_ids == ("first-a0", "second-a0", "third-a0", "fourth-a0")
    assert [
        item["work_package_id"]
        for item in result["outcomes"]["build"]["attempts"]
        if item["stage"] == "worker"
    ] == ["first", "second", "third", "fourth"]


async def test_sync_ready_task_runs_exclusively_and_async_capacity_is_two():
    services = AsyncServices(
        [package("sync", mode="sync"), package("first"), package("second"), package("third")]
    )
    active_at_start = {}

    async def observe(work):
        active_at_start[work.work_package_id] = services.world["active"]
        if work.work_package_id == "first":
            await services.started["second"].wait()

    services.before_execute = observe
    _, result = await run(services)
    assert result["status"] == "completed"
    assert services.world["order"][0] == "sync" and active_at_start["sync"] == 1
    assert services.world["max_active"] == 2 and services.world["counts"] == Counter(
        sync=1, first=1, second=1, third=1
    )


@pytest.mark.parametrize("failed", [("first",), ("first", "second")])
async def test_rejected_branch_retry_retains_successful_sibling_and_uses_one_shared_wave_revision(
    failed,
):
    services = AsyncServices([package("first"), package("second")])
    services.reject = lambda deliverable, _criteria: (
        not deliverable.worker_role.endswith("_head")
        and any(deliverable.artifact_ids == (f"{name}-a0",) for name in failed)
    )
    _, result = await run(services)
    assert result["status"] == "completed" and result["epochs"] == {"build": 0}
    assert services.world["counts"] == Counter(
        {"first": 2, "second": 2 if "second" in failed else 1}
    )
    assert {work.execution_attempt for work, *_ in services.executions} == {0, 1}
    accepted = result["outcomes"]["build"]["deliverable"]["artifact_ids"]
    assert accepted == ["first-a1", "second-a1" if "second" in failed else "second-a0"]


async def test_optional_fallback_does_not_block_other_work_or_become_success_evidence():
    services = AsyncServices(
        [
            package("optional", critical=False),
            package("mandatory"),
            package("integrate", ("optional", "mandatory"), mode="sync"),
        ]
    )
    services.optional.add("optional")
    _, result = await run(services)
    assert result["status"] == "completed"
    combined = result["outcomes"]["build"]["deliverable"]
    assert "optional-a0" not in combined["artifact_ids"] and not combined["fallback"]
    integration = next(
        deps for work, deps, *_ in services.executions if work.work_package_id == "integrate"
    )
    assert integration[0].fallback and not integration[1].fallback


@pytest.mark.parametrize("control", ["cancel", "constitution_violation"])
async def test_cancel_or_policy_halt_prevents_dispatch_of_downstream_tasks(control):
    services = AsyncServices(
        [package("first"), package("second"), package("downstream", ("first", "second"))]
    )

    async def stop(work):
        if work.work_package_id == "first":
            if control == "cancel":
                services.command = "cancel"
            else:
                raise EscalationSignal("constitution_violation", "Recorded prohibited action")

    services.before_execute = stop
    _, result = await run(services)
    assert "downstream" not in services.world["counts"]
    assert result["status"] == ("cancelled" if control == "cancel" else "awaiting_review")
    if control != "cancel":
        assert result["review"]["kind"] == "constitution_violation"


async def test_legacy_missing_dependency_fields_preserve_order_and_all_earlier_inputs():
    plans = [package(name, None, mode="sync") for name in ("first", "second", "third")]
    assert normalized_work_dependencies(plans) == {
        "first": (),
        "second": ("first",),
        "third": ("first", "second"),
    }
    services = AsyncServices(plans)
    _, result = await run(services)
    assert result["status"] == "completed" and services.world["max_active"] == 1
    assert services.world["order"] == ["first", "second", "third"]
    assert [item.artifact_ids[0] for item in services.executions[-1][1]] == [
        "first-a0",
        "second-a0",
    ]


@pytest.mark.integration
async def test_postgres_resume_keeps_completed_parallel_sibling_and_persisted_dispatch(
    postgres_url,
):
    world = {"counts": Counter(), "order": [], "active": 0, "max_active": 0}
    plans = [package("first"), package("second")]
    first = AsyncServices(plans, world=world)
    first.limits = RunLimits(max_model_calls=None, worker_model_calls=None, max_tool_calls=None)
    async with AsyncPostgresSaver.from_conn_string(postgres_url) as saver:
        await saver.setup()

        async def fail_after_saved_sibling(work):
            if work.work_package_id != "second":
                return
            async with asyncio.timeout(5):
                while True:
                    saved = [entry async for entry in saver.alist(None, limit=100)]
                    if any(
                        channel == "work_results" and isinstance(value, dict) and "first" in value
                        for entry in saved
                        for _task, channel, value in entry.pending_writes
                    ):
                        break
                    await asyncio.sleep(0.01)
            raise AutonomousCheckpointYield("Private task paused at its saved boundary")

        first.before_execute = fail_after_saved_sibling
        graph = build_graph(first, checkpointer=saver)
        with pytest.raises(AutonomousCheckpointYield):
            await graph.ainvoke(
                initial_state(RUN, "Build requested output", Constitution()),
                runtime_config(RUN),
                durability="sync",
            )
    restored = AsyncServices(
        [work.model_copy(update={"task": "An unrequested replacement"}) for work in plans],
        world=world,
    )
    restored.limits = first.limits
    async with AsyncPostgresSaver.from_conn_string(postgres_url) as saver:
        graph = build_graph(restored, checkpointer=saver)
        result = await graph.ainvoke(None, runtime_config(RUN), durability="sync")
    assert result["status"] == "completed" and world["counts"] == Counter(first=1, second=2)
    assert restored.executions[0][0].task == "Produce second"
    assert result["epochs"] == {"build": 0}
