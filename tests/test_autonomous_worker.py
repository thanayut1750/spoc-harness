"""Durable wakeups span simulated days and restart without human approval."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg import OperationalError
from test_autonomous_runtime import AutonomousServices

import org_harness.runtime as runtime_module
import org_harness.storage as storage_module
import org_harness.worker as worker_module
from org_harness.autonomy import AutonomousCheckpointYield
from org_harness.config import Settings
from org_harness.models import EscalationSignal, RunCreate, RunLimits
from org_harness.storage import MemoryStorage, PostgresStorage
from org_harness.worker import Worker, migrate

UNLIMITED = RunLimits(max_model_calls=None, worker_model_calls=None, max_tool_calls=None)


class Clock(datetime):
    instant = datetime(2026, 1, 1, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        return cls.instant if tz else cls.instant.replace(tzinfo=None)


class ScheduledServices(AutonomousServices):
    def __init__(self, settings, storage, run, world):
        super().__init__()
        self.settings, self.storage, self.run, self.world = settings, storage, run, world
        self.limits = RunLimits.model_validate(run["limits"])

    async def control(self):
        run = await self.storage.get_run(self.run["run_id"])
        return (
            "cancel"
            if run.get("cancel_requested")
            else "pause"
            if run.get("pause_requested")
            else "suspend"
            if run.get("governance_halt")
            else None
        )

    async def execute(self, *args):
        await self.storage.reserve_budget(self.run["run_id"], "model")
        await self.storage.reserve_budget(self.run["run_id"], "tool")
        self.world.executions.append((self.run["run_id"], args[-1]))
        if self.run["user_request"] != "Another mission" and Clock.instant < self.world.ready:
            raise EscalationSignal("worker_timeout", "Upstream resource is temporarily unavailable")
        return await super().execute(*args)

    async def emit(self, agent_id, activity, summary, **data):
        await self.storage.emit(
            {
                "source": "harness",
                "agent_id": agent_id,
                "run_id": self.run["run_id"],
                "kr_id": data.pop("kr_id", None),
                "activity": activity,
                "summary": summary[:2000],
                "data": data,
            }
        )

    async def close(self):
        self.world.closed += 1


def settings(tmp_path, **updates):
    return Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path, **updates)


def worker_for(storage, saver, config, world):
    return Worker(
        config,
        storage,
        checkpointer=saver,
        services_factory=lambda cfg, db, run: ScheduledServices(cfg, db, run, world),
    )


async def test_automatic_repair_survives_two_and_seven_days_and_releases_queue_for_other_missions(
    tmp_path, monkeypatch
):
    Clock.instant = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(storage_module, "datetime", Clock)
    storage, saver = MemoryStorage(), InMemorySaver()
    config = settings(tmp_path)
    world = SimpleNamespace(ready=Clock.instant + timedelta(days=7), executions=[], closed=0)
    run = await storage.create_run(
        RunCreate(user_request="Continue until the resource recovers", limits=UNLIMITED).model_dump(
            mode="json"
        )
    )
    assert await worker_for(storage, saver, config, world).run_once()
    waiting = await storage.get_run(run["run_id"])
    assert waiting["status"] == "queued" and waiting["review"] is None
    assert waiting["automatic_cycles"] == 1 and waiting["epochs"]["direct-1"] == 1
    assert not await worker_for(storage, saver, config, world).run_once()
    other = await storage.create_run(
        RunCreate(user_request="Another mission").model_dump(mode="json")
    )
    assert await worker_for(storage, saver, config, world).run_once()
    assert (await storage.get_run(other["run_id"]))["status"] == "succeeded"
    Clock.instant += timedelta(days=2)
    assert await worker_for(storage, saver, config, world).run_once()
    waiting = await storage.get_run(run["run_id"])
    assert waiting["status"] == "queued" and waiting["review"] is None
    assert waiting["automatic_cycles"] == 2
    assert waiting["continuation"]["attempt"] == 2
    Clock.instant += timedelta(days=5)
    assert await worker_for(storage, saver, config, world).run_once()
    completed = await storage.get_run(run["run_id"])
    assert completed["status"] == "succeeded" and completed["review"] is None
    assert completed["limits"] == run["limits"] and completed["constitution"] == run["constitution"]
    assert completed["model_calls"] == completed["tool_calls"] == 3
    assert [epoch for actor, epoch in world.executions if actor == run["run_id"]] == [0, 1, 2]
    assert world.closed == 4


class ChunkState(TypedDict, total=False):
    run_id: str
    status: str
    report: str
    index: int


def chunk_graph(world, *, recursive=False):
    def factory(services, *, checkpointer=None, store=None):
        def prepare(_state):
            world.prepared += 1
            assert services.agent_checkpointer is checkpointer
            return {"status": "running", "index": 0}

        async def execute(state):
            world.calls += 1
            if not recursive and world.calls == 1:
                if before_yield := getattr(world, "before_yield", None):
                    await before_yield()
                raise AutonomousCheckpointYield("Private agent reached its safe work boundary")
            index = state["index"] + 1
            return {
                "index": index,
                "status": "completed" if not recursive or index >= 6 else "running",
                "report": "Recorded work completed",
            }

        builder = (
            StateGraph(ChunkState)
            .add_node("prepare", prepare)
            .add_node("execute", execute)
            .add_edge(START, "prepare")
            .add_edge("prepare", "execute")
        )
        builder.add_conditional_edges(
            "execute", lambda state: END if state["status"] == "completed" else "execute"
        )
        return builder.compile(checkpointer=checkpointer, store=store)

    return factory


def simple_factory(world):
    def create(_config, _storage, run):
        async def close():
            world.closed += 1

        return SimpleNamespace(run=run, close=close)

    return create


async def test_healthy_private_chunk_requeues_immediately_and_resumes_same_checkpoint(tmp_path):
    storage, saver = MemoryStorage(), InMemorySaver()
    world = SimpleNamespace(prepared=0, calls=0, closed=0)
    run = await storage.create_run(
        RunCreate(user_request="Continue bounded chunks", limits=UNLIMITED).model_dump(mode="json")
    )
    for _ in range(2):
        worker = Worker(
            settings(tmp_path),
            storage,
            checkpointer=saver,
            services_factory=simple_factory(world),
            graph_factory=chunk_graph(world),
        )
        assert await worker.run_once()
    current = await storage.get_run(run["run_id"])
    assert current["status"] == "succeeded" and current["review"] is None
    assert world.prepared == 1 and world.calls == 2 and world.closed == 2
    assert current["autonomous_failures"] == 0


async def test_pause_during_private_chunk_stays_paused_until_explicit_continue(tmp_path):
    storage, saver = MemoryStorage(), InMemorySaver()
    world = SimpleNamespace(prepared=0, calls=0, closed=0)
    run = await storage.create_run(
        RunCreate(user_request="Pause a healthy checkpoint", limits=UNLIMITED).model_dump(
            mode="json"
        )
    )

    async def pause():
        await storage.command(run["run_id"], "pause", {})

    world.before_yield = pause

    def worker():
        return Worker(
            settings(tmp_path),
            storage,
            checkpointer=saver,
            services_factory=simple_factory(world),
            graph_factory=chunk_graph(world),
        )

    assert await worker().run_once()
    paused = await storage.get_run(run["run_id"])
    assert paused["status"] == "paused"
    assert paused["review"]["kind"] == "manual_pause" and world.calls == 1
    assert not await worker().run_once()
    await storage.command(
        run["run_id"],
        "resume",
        {"action": "continue", "interrupt_id": paused["review"]["interrupt_id"]},
    )
    assert await worker().run_once()
    assert (await storage.get_run(run["run_id"]))["status"] == "succeeded"
    assert world.prepared == 1 and world.calls == 2


async def test_legacy_pending_command_is_reconciled_before_service_setup_without_reexecution(
    tmp_path,
):
    storage, saver = MemoryStorage(), InMemorySaver()
    marker = tmp_path / "must-not-run.txt"
    run = await storage.create_run(
        RunCreate(user_request="Inspect uncertain effects", limits=UNLIMITED).model_dump(
            mode="json"
        )
    )
    await storage.begin_operation(
        run["run_id"], "legacy-command", "command", {"command": f"touch {marker}"}
    )
    world = SimpleNamespace(prepared=0, calls=1, closed=0)
    original = simple_factory(world)

    def factory(config, db, current):
        recoveries = current["autonomous_command_recoveries"]
        assert len(recoveries) == 1
        assert recoveries[0]["operation_id"] == "legacy-command"
        assert recoveries[0]["result"]["effects_uncertain"]
        assert recoveries[0]["result"]["execution_stopped"] is False
        assert recoveries[0]["result"]["exit_code"] != 0
        assert not marker.exists()
        return original(config, db, current)

    assert await Worker(
        settings(tmp_path),
        storage,
        checkpointer=saver,
        services_factory=factory,
        graph_factory=chunk_graph(world),
    ).run_once()
    current = await storage.get_run(run["run_id"])
    assert current["status"] == "succeeded" and current["review"] is None
    assert not await storage.uncertain_operations(run["run_id"])
    assert storage.operations["legacy-command"]["status"] == "done"
    assert not marker.exists()


async def test_graph_recursion_limit_resumes_pending_checkpoint_instead_of_resetting_work(
    tmp_path, monkeypatch
):
    Clock.instant = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(storage_module, "datetime", Clock)
    original_config = runtime_module.runtime_config
    monkeypatch.setattr(
        runtime_module,
        "runtime_config",
        lambda run_id: {**original_config(run_id), "recursion_limit": 3},
    )
    storage, saver = MemoryStorage(), InMemorySaver()
    world = SimpleNamespace(prepared=0, calls=0, closed=0)
    run = await storage.create_run(
        RunCreate(user_request="Graph work crosses a step boundary", limits=UNLIMITED).model_dump(
            mode="json"
        )
    )
    first = Worker(
        settings(tmp_path),
        storage,
        checkpointer=saver,
        services_factory=simple_factory(world),
        graph_factory=chunk_graph(world, recursive=True),
    )
    assert await first.run_once()
    waiting = await storage.get_run(run["run_id"])
    assert waiting["status"] == "queued" and waiting["review"] is None
    assert waiting["autonomous_failures"] == 1
    monkeypatch.setattr(runtime_module, "runtime_config", original_config)
    Clock.instant += timedelta(days=2)
    restored = Worker(
        settings(tmp_path),
        storage,
        checkpointer=saver,
        services_factory=simple_factory(world),
        graph_factory=chunk_graph(world, recursive=True),
    )
    assert await restored.run_once()
    assert (await storage.get_run(run["run_id"]))["status"] == "succeeded"
    assert world.prepared == 1 and world.calls == 6


async def test_existing_nonmanual_review_is_adopted_after_all_three_caps_become_unlimited(
    tmp_path, monkeypatch
):
    Clock.instant = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(storage_module, "datetime", Clock)
    storage, saver = MemoryStorage(), InMemorySaver()
    world = SimpleNamespace(ready=Clock.instant + timedelta(days=7), executions=[], closed=0)
    run = await storage.create_run(
        RunCreate(user_request="Previously finite interrupted mission").model_dump(mode="json")
    )
    assert await worker_for(storage, saver, settings(tmp_path), world).run_once()
    assert (await storage.get_run(run["run_id"]))["status"] == "review"
    await storage.command(
        run["run_id"],
        "budgets",
        {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None},
    )
    assert await worker_for(storage, saver, settings(tmp_path), world).run_once()
    waiting = await storage.get_run(run["run_id"])
    assert waiting["status"] == "queued" and waiting["review"] is None
    Clock.instant += timedelta(days=7)
    assert await worker_for(storage, saver, settings(tmp_path), world).run_once()
    assert (await storage.get_run(run["run_id"]))["status"] == "succeeded"


@pytest.mark.integration
async def test_private_chunk_checkpoint_survives_postgres_storage_and_saver_restart(
    postgres_url, tmp_path
):
    config = settings(tmp_path, database_url=postgres_url)
    await migrate(config)
    storage = PostgresStorage(postgres_url)
    await storage.open()
    world = SimpleNamespace(prepared=0, calls=0, closed=0)
    try:
        run = await storage.create_run(
            RunCreate(user_request="Recover checkpoint from Postgres", limits=UNLIMITED).model_dump(
                mode="json"
            )
        )
        async with AsyncPostgresSaver.from_conn_string(postgres_url) as saver:
            assert await Worker(
                config,
                storage,
                checkpointer=saver,
                services_factory=simple_factory(world),
                graph_factory=chunk_graph(world),
            ).run_once()
            waiting = await storage.get_run(run["run_id"])
            assert waiting["status"] == "queued" and waiting["review"] is None
    finally:
        await storage.close()
    reopened = PostgresStorage(postgres_url)
    await reopened.open()
    try:
        async with AsyncPostgresSaver.from_conn_string(postgres_url) as saver:
            assert await Worker(
                config,
                reopened,
                checkpointer=saver,
                services_factory=simple_factory(world),
                graph_factory=chunk_graph(world),
            ).run_once()
        assert (await reopened.get_run(run["run_id"]))["status"] == "succeeded"
        assert world.prepared == 1 and world.calls == 2
    finally:
        await reopened.close()


class ReconnectingStorage(MemoryStorage):
    def __init__(self):
        super().__init__()
        self.opens = self.closes = 0
        self.failed_updates = []
        self.reserve_attempts = 0
        self.completed = asyncio.Event()

    async def open(self):
        self.opens += 1

    async def close(self):
        self.closes += 1

    async def reserve_budget(self, *args, **kwargs):
        self.reserve_attempts += 1
        if self.reserve_attempts == 1:
            raise OperationalError("Simulated temporary database disconnect")
        return await super().reserve_budget(*args, **kwargs)

    async def update_run(self, run_id, **fields):
        if fields.get("status") == "failed":
            self.failed_updates.append(fields)
        result = await super().update_run(run_id, **fields)
        if result["status"] == "succeeded":
            self.completed.set()
        return result


async def test_temporary_database_loss_reconnects_without_failing_or_resetting_the_mission(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(worker_module, "retry_delay", lambda _attempt: 0)
    storage = ReconnectingStorage()
    world = SimpleNamespace(ready=datetime.min.replace(tzinfo=UTC), executions=[], closed=0)
    run = await storage.create_run(
        RunCreate(user_request="Recover database visibility", limits=UNLIMITED).model_dump(
            mode="json"
        )
    )
    worker = worker_for(storage, None, settings(tmp_path), world)
    task = asyncio.create_task(worker.run_forever())
    try:
        await asyncio.wait_for(storage.completed.wait(), 5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    current = await storage.get_run(run["run_id"])
    assert current["status"] == "succeeded" and current["review"] is None
    assert current["epochs"]["direct-1"] == 0
    assert not storage.failed_updates
    assert storage.opens >= 2 and storage.closes >= 2
    assert len(world.executions) == 1 and world.closed == 2
    assert current["model_calls"] == current["tool_calls"] == 1


async def test_missing_migration_and_programming_errors_are_not_retried(tmp_path):
    class Unmigrated(MemoryStorage):
        async def ready(self, *, raise_errors=False):
            return False

    with pytest.raises(RuntimeError, match="spoc migrate"):
        await Worker(settings(tmp_path), Unmigrated()).run_forever()

    class BrokenWorker(Worker):
        async def _open_runtime_resources(self, stack):
            raise KeyError("Unexpected programming failure")

    with pytest.raises(KeyError, match="Unexpected programming failure"):
        await BrokenWorker(settings(tmp_path), MemoryStorage()).run_forever()


async def test_monitor_lease_loss_releases_job_and_next_worker_resumes_without_reinitialization(
    tmp_path,
):
    storage, saver = MemoryStorage(), InMemorySaver()
    world = SimpleNamespace(prepared=0, calls=0, closed=0)
    entered = asyncio.Event()

    async def ownership_lost():
        entered.set()
        await asyncio.Event().wait()

    world.before_yield = ownership_lost
    run = await storage.create_run(
        RunCreate(user_request="Recover lost worker ownership", limits=UNLIMITED).model_dump(
            mode="json"
        )
    )

    class LosingWorker(Worker):
        async def _monitor(self, run_id, task, lock_session):
            await entered.wait()
            task.cancel()

    assert await LosingWorker(
        settings(tmp_path),
        storage,
        checkpointer=saver,
        services_factory=simple_factory(world),
        graph_factory=chunk_graph(world),
    ).run_once()
    assert (await storage.get_run(run["run_id"]))["status"] == "running"
    assert await Worker(
        settings(tmp_path),
        storage,
        checkpointer=saver,
        services_factory=simple_factory(world),
        graph_factory=chunk_graph(world),
    ).run_once()
    assert (await storage.get_run(run["run_id"]))["status"] == "succeeded"
    assert world.prepared == 1 and world.calls == 2


@pytest.mark.parametrize("phase", ["worker", "department"])
@pytest.mark.parametrize("kind", ["provider_error", "invalid_output"])
async def test_gate_provider_failure_resumes_exact_pending_review_without_reexecuting_work(
    tmp_path, monkeypatch, phase, kind
):
    Clock.instant = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(storage_module, "datetime", Clock)
    storage, saver = MemoryStorage(), InMemorySaver()
    world = SimpleNamespace(
        ready=datetime.min.replace(tzinfo=UTC), executions=[], closed=0, failures=0
    )

    class GateServices(ScheduledServices):
        def __init__(self, *args):
            super().__init__(*args)
            self.decision = self.decision.model_copy(
                update={"mode": "FULL_PYRAMID", "departments": ("research", "engineering")}
            )

        async def evaluate(self, deliverable, criteria, constitution):
            await self.storage.reserve_budget(self.run["run_id"], "model")
            current_phase = "department" if deliverable.worker_role.endswith("_head") else "worker"
            if current_phase == phase and world.failures == 0:
                world.failures += 1
                raise EscalationSignal(kind, "Review service temporarily unavailable")
            return await super().evaluate(deliverable, criteria, constitution)

    run = await storage.create_run(
        RunCreate(
            user_request="Retain completed work during review outage", limits=UNLIMITED
        ).model_dump(mode="json")
    )

    def worker():
        return Worker(
            settings(tmp_path),
            storage,
            checkpointer=saver,
            services_factory=lambda cfg, db, current: GateServices(cfg, db, current, world),
        )

    assert await worker().run_once()
    first = await storage.get_run(run["run_id"])
    assert first["status"] == "queued" and first["review"] is None
    assert first["autonomous_failures"] == 1 and first["epochs"] == {"research": 0}
    assert len(world.executions) == 1
    Clock.instant += timedelta(minutes=5)
    assert await worker().run_once()
    completed = await storage.get_run(run["run_id"])
    assert completed["status"] == "succeeded" and completed["review"] is None
    assert completed["epochs"] == {"research": 0}
    assert len(world.executions) == 1 and world.closed == 2
    assert completed["model_calls"] == 4 and completed["tool_calls"] == 1


@pytest.mark.integration
async def test_production_database_resources_reopen_and_resume_the_saved_checkpoint(
    postgres_url, tmp_path, monkeypatch
):
    monkeypatch.setattr(worker_module, "retry_delay", lambda _attempt: 0)
    config = settings(tmp_path, database_url=postgres_url)
    await migrate(config)
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        run = await storage.create_run(
            RunCreate(
                user_request="Reopen independent saver and store", limits=UNLIMITED
            ).model_dump(mode="json")
        )
    finally:
        await storage.close()
    world = SimpleNamespace(prepared=0, calls=0, closed=0)
    done = asyncio.Event()

    class ReopeningWorker(Worker):
        async def run_once(self):
            if not hasattr(self, "original_saver"):
                self.original_saver, self.original_store = self.checkpointer, self.store
                assert await super().run_once()
                await self.checkpointer.conn.close()
                raise OperationalError("A saved database connection was lost")
            assert self.checkpointer is not self.original_saver
            assert self.store is not self.original_store
            result = await super().run_once()
            if result:
                done.set()
            return result

    worker = ReopeningWorker(
        config,
        services_factory=simple_factory(world),
        graph_factory=chunk_graph(world),
    )
    task = asyncio.create_task(worker.run_forever())
    try:
        await asyncio.wait_for(done.wait(), 8)
        current = await worker.storage.get_run(run["run_id"])
        assert current["status"] == "succeeded" and current["review"] is None
        assert world.prepared == 1 and world.calls == 2
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
