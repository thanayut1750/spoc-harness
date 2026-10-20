"""Leased host worker with durable graph checkpoints and explicit recovery."""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Callable
from contextlib import AsyncExitStack, suppress
from pathlib import Path
from uuid import uuid4

from langgraph.errors import GraphRecursionError
from psycopg import InterfaceError, OperationalError
from psycopg.errors import UndefinedTable
from psycopg_pool import PoolClosed, PoolTimeout

from org_harness.autonomy import AutonomousCheckpointYield, autonomous_mode, retry_delay
from org_harness.config import Settings, configure_tracing
from org_harness.storage import ConflictError, MemoryStorage, PostgresStorage, create_storage

logger = logging.getLogger(__name__)
CONNECTION_ERRORS = (OperationalError, InterfaceError, PoolTimeout, PoolClosed)
STATUS_MAP = {"completed": "succeeded", "awaiting_review": "review"}
GRAPH_FIELDS = (
    "objectives",
    "progress",
    "outcomes",
    "epochs",
    "report",
    "attempt_history",
    "auto_replans",
    "triage",
    "execution_mode",
    "active_departments",
    "revision_limit",
    "automatic_cycles",
    "autonomous_policy_repairs",
)


def command_recovery_summary(receipt: dict) -> dict:
    """Keep model/run projections compact; exact output remains in the journal."""
    result = receipt.get("result", {})
    public = {
        key: result[key]
        for key in (
            "status",
            "exit_code",
            "interrupted",
            "effects_uncertain",
            "execution_stopped",
            "process_state",
            "artifact_ids",
        )
        if key in result
    }
    if "recovery_guidance" in result:
        public["recovery_guidance"] = str(result["recovery_guidance"])[:2000]
    return {"operation_id": receipt["operation_id"], "result": public}


async def migrate(settings: Settings) -> None:
    """Migration is an operator action, never an API startup side effect."""
    storage = create_storage(settings)
    await storage.open()
    try:
        if isinstance(storage, MemoryStorage):
            return
        await storage.migrate()
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres import AsyncPostgresStore

        url = settings.database_url.get_secret_value()
        async with AsyncPostgresSaver.from_conn_string(url) as saver:
            await saver.setup()
        async with AsyncPostgresStore.from_conn_string(url) as store:
            await store.setup()
    finally:
        await storage.close()


class Worker:
    def __init__(
        self,
        settings: Settings,
        storage=None,
        *,
        services_factory=None,
        graph_factory=None,
        checkpointer=None,
        store=None,
    ) -> None:
        self.settings = settings
        self.storage = storage or create_storage(settings)
        # Recreate only a known database adapter; arbitrary injected test backends
        # and checkpointers remain caller-owned across reconnect attempts.
        self._storage_factory: Callable[[], MemoryStorage | PostgresStorage] | None = None
        if storage is None:
            self._storage_factory = lambda: create_storage(settings)
        elif type(storage) is PostgresStorage and isinstance(storage.pool.conninfo, str):
            connection_info = storage.pool.conninfo
            self._storage_factory = lambda: PostgresStorage(connection_info)
        self.worker_id = str(uuid4())
        self.services_factory = services_factory
        self.graph_factory = graph_factory
        self.checkpointer = checkpointer
        self.store = store
        if hasattr(self.storage, "register_runtime_resources") and checkpointer is not None:
            self.storage.register_runtime_resources(checkpointer, store)

    async def run_once(self) -> bool:
        async with self.storage.worker_lock() as lock_session:
            if not lock_session:
                return False
            run = await self.storage.claim_job(self.worker_id)
            if not run:
                return False
            task = asyncio.create_task(self.execute(run))
            monitor = asyncio.create_task(self._monitor(run["run_id"], task, lock_session))
            try:
                await task
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
                # The monitor cancels only the execution task on lease or
                # database loss. This is distinct from operator shutdown of
                # run_forever itself, which must propagate cancellation.
                logger.info("Worker ownership lost; saved execution remains recoverable")
            finally:
                monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await monitor
                await self.storage.finish_job(run["run_id"], self.worker_id)
            return True

    async def _monitor(self, run_id, task, lock_session):
        ticks = 0
        try:
            while not task.done():
                await asyncio.sleep(0.25)
                run = await self.storage.get_run(run_id)
                if run.get("cancel_requested"):
                    task.cancel()
                    return
                ticks += 1
                if ticks >= 20:
                    ticks = 0
                    if lock_session is not True:
                        await lock_session.execute("SELECT 1")
                    if not await self.storage.heartbeat(run_id, self.worker_id):
                        task.cancel()
                        return
        except Exception:
            # Losing storage visibility also loses the ability to honor cancellation
            # and prove exclusive ownership. Cancel graph and host subprocesses.
            task.cancel()
            raise

    async def execute(self, run: dict) -> None:
        from langgraph.types import Command

        from org_harness.runtime import (
            build_graph,
            enrich_review_context,
            initial_state,
            runtime_config,
        )

        run_id = run["run_id"]
        services = None
        graph = None
        config = runtime_config(run_id)
        automatic = autonomous_mode(run.get("limits"))
        phase = "operation_preflight"
        try:
            if automatic:
                from org_harness.tools import reconcile_pending_commands

                reconciled = await reconcile_pending_commands(self.settings, self.storage, run)
                if reconciled:
                    run = await self.storage.update_run(
                        run_id,
                        autonomous_command_recoveries=[
                            command_recovery_summary(item)
                            for item in [
                                *run.get("autonomous_command_recoveries", []),
                                *reconciled,
                            ][-16:]
                        ],
                    )
            uncertain = await self.storage.uncertain_operations(run_id)
            if uncertain:
                operation = uncertain[0]
                if automatic:
                    await self.storage.update_run(
                        run_id,
                        status="failed",
                        review=None,
                        error="An interrupted host command has an unknown outcome; automatic replay is unsafe.",
                        failure_context={
                            "phase": "operation_preflight",
                            "type": "unknown_operation",
                            "operation_id": operation["operation_id"],
                        },
                    )
                    await self.storage.emit(
                        {
                            "run_id": run_id,
                            "agent_id": "executive",
                            "activity": "error",
                            "summary": "Stopped safely: an interrupted command requires outcome reconciliation",
                        }
                    )
                    return
                await self.storage.update_run(
                    run_id,
                    status="review",
                    review=enrich_review_context(
                        {
                            "interrupt_id": f"operation:{operation['operation_id']}",
                            "kind": "unknown_operation",
                            "reason": "A host command was interrupted; its outcome is unknown.",
                            "operation_id": operation["operation_id"],
                            "kr_ids": [],
                            "allowed_actions": ["retry_operation", "abort"],
                            "operation": {
                                "operation_id": operation["operation_id"],
                                "status": operation.get("status", "pending"),
                                "command": str(operation.get("request", {}).get("command", ""))[
                                    :2000
                                ],
                                "cwd": str(operation.get("request", {}).get("cwd", ""))[:1000],
                            },
                        },
                        run,
                    ),
                )
                await self.storage.emit(
                    {
                        "run_id": run_id,
                        "agent_id": "executive",
                        "activity": "waiting",
                        "summary": "Review required before retrying an interrupted command",
                    }
                )
                return
            phase = "service_setup"
            if self.services_factory is None:
                from org_harness.agent_services import AgentServices

                services = AgentServices(self.settings, self.storage, run)
            else:
                services = self.services_factory(self.settings, self.storage, run)
            if hasattr(services, "__dict__"):
                services.agent_checkpointer = self.checkpointer
            graph = (self.graph_factory or build_graph)(
                services, checkpointer=self.checkpointer, store=self.store
            )
            phase = "checkpoint_load"
            snapshot = await graph.aget_state(config)
            if (
                automatic
                and snapshot.values
                and not snapshot.next
                and snapshot.values.get("status") == "failed"
                and "plan" in graph.get_graph().nodes
            ):
                # An explicit retry of a formerly finite, finished failure may
                # reconsider blocked work while retaining its approved outcomes.
                has_objectives = bool(snapshot.values.get("objectives"))
                await graph.aupdate_state(
                    config,
                    {
                        "status": "running",
                        "route": "coordinate" if has_objectives else "plan",
                        "review": None,
                    },
                    as_node="plan" if has_objectives else "triage",
                )
                snapshot = await graph.aget_state(config)
            if snapshot.values and not snapshot.next and snapshot.values.get("status") == "failed":
                message = (
                    "The saved workflow already ended in failure and has no pending checkpoint. "
                    "Submit a new run to execute the objective again; recorded evidence is retained."
                )
                await self.storage.update_run(run_id, status="failed", error=message)
                await self.storage.emit(
                    {
                        "run_id": run_id,
                        "agent_id": "executive",
                        "activity": "error",
                        "summary": message,
                    }
                )
                return
            interrupts = tuple(getattr(snapshot, "interrupts", ()))
            decision = run.get("resume_decision")
            graph_input: object
            internal = interrupts and all(
                isinstance(item.value, dict) and item.value.get("kind") == "automatic_cycle"
                for item in interrupts
            )
            legacy_automatic = (
                automatic
                and interrupts
                and not decision
                and all(
                    isinstance(item.value, dict) and item.value.get("kind") != "manual_pause"
                    for item in interrupts
                )
            )
            if internal or legacy_automatic:
                graph_input = Command(resume={item.id: {"automatic": True} for item in interrupts})
            elif decision and interrupts:
                graph_input = Command(resume=decision)
            elif snapshot.values:
                graph_input = None
            else:
                graph_input = initial_state(run_id, run["user_request"], run["constitution"])
            await self.storage.update_run(run_id, resume_decision=None, review=None)
            await self.storage.emit(
                {
                    "run_id": run_id,
                    "agent_id": "executive",
                    "activity": "waiting",
                    "summary": "Recovering execution" if snapshot.values else "Starting execution",
                }
            )
            phase = "graph_execution"
            async for values in graph.astream(
                graph_input, config, stream_mode="values", durability="sync"
            ):
                projection = {key: values[key] for key in GRAPH_FIELDS if key in values}
                if projection:
                    await self.storage.update_run(run_id, **projection)
            phase = "checkpoint_finalize"
            snapshot = await graph.aget_state(config)
            values = dict(snapshot.values)
            fields = {key: values[key] for key in (*GRAPH_FIELDS, "review") if key in values}
            interrupts = tuple(getattr(snapshot, "interrupts", ()))
            if (
                interrupts
                and automatic
                and all(
                    isinstance(item.value, dict) and item.value.get("kind") == "automatic_cycle"
                    for item in interrupts
                )
            ):
                payload = interrupts[0].value
                failures = int(run.get("autonomous_failures", 0)) + 1
                await self._schedule_continuation(
                    run,
                    values,
                    str(payload.get("reason", "Automatic repair checkpoint")),
                    retry_delay(failures),
                    failures,
                )
                return
            if interrupts:
                review = dict(fields.get("review") or interrupts[0].value or {})
                review["interrupt_id"] = interrupts[0].id
                review = enrich_review_context(review, {**run, **values})
                fields.update(
                    review=review,
                    status="paused" if review.get("kind") == "manual_pause" else "review",
                )
            else:
                fields["status"] = STATUS_MAP.get(
                    str(values.get("status", "failed")), str(values.get("status", "failed"))
                )
                if fields["status"] == "running":
                    # A graph that exhausted steps without a terminal state must not be reported complete.
                    fields["status"] = "failed"
            result = await self.storage.update_run(run_id, **fields)
            await self.storage.emit(
                {
                    "run_id": run_id,
                    "agent_id": "executive",
                    "activity": {
                        "succeeded": "completed",
                        "failed": "error",
                        "cancelled": "idle",
                        "aborted": "idle",
                    }.get(result["status"], "waiting"),
                    "summary": f"Run {result['status']}",
                }
            )
        except (AutonomousCheckpointYield, GraphRecursionError) as exc:
            if automatic and graph is None and isinstance(exc, AutonomousCheckpointYield):
                failures = (
                    int(run.get("autonomous_failures", 0)) + 1
                    if getattr(exc, "recoverable_failure", False)
                    else 0
                )
                await self._schedule_continuation(run, run, exc.reason, exc.delay_seconds, failures)
                return
            if not automatic or graph is None:
                await self._record_failure(run_id, phase, exc)
                return
            uncertain = await self.storage.uncertain_operations(run_id)
            if uncertain:
                await self.storage.update_run(
                    run_id,
                    status="failed",
                    review=None,
                    error="An interrupted command must be reconciled before automatic continuation.",
                    failure_context={
                        "phase": "operation_preflight",
                        "type": "unknown_operation",
                        "operation_id": uncertain[0]["operation_id"],
                    },
                )
                return
            snapshot = await graph.aget_state(config)
            values = dict(snapshot.values)
            if not snapshot.next:
                # Re-enter only the deterministic coordinator, preserving every
                # verified outcome. Do not rerun a finished child assignment.
                if "plan" not in graph.get_graph().nodes:
                    await self._record_failure(run_id, phase, exc)
                    return
                await graph.aupdate_state(
                    config,
                    {"status": "running", "route": "coordinate", "review": None},
                    as_node="plan",
                )
                values = dict((await graph.aget_state(config)).values)
            healthy = isinstance(exc, AutonomousCheckpointYield) and not getattr(
                exc, "recoverable_failure", False
            )
            failures = 0 if healthy else int(run.get("autonomous_failures", 0)) + 1
            reason = (
                exc.reason
                if isinstance(exc, AutonomousCheckpointYield)
                else "Graph step checkpoint reached; continuing saved work"
            )
            delay = (
                exc.delay_seconds
                if isinstance(exc, AutonomousCheckpointYield)
                else retry_delay(failures)
            )
            await self._schedule_continuation(
                run,
                values,
                reason,
                delay,
                failures,
            )
        except asyncio.CancelledError:
            current = await self.storage.get_run(run_id)
            if current.get("cancel_requested"):
                await self.storage.update_run(run_id, status="cancelled")
                await self.storage.emit(
                    {
                        "run_id": run_id,
                        "agent_id": "executive",
                        "activity": "idle",
                        "summary": "Run cancelled",
                    }
                )
            else:
                # Retain running state for checkpoint recovery after shutdown/lost lease.
                logger.info("Execution interrupted; checkpoint recovery remains available")
                raise
        except CONNECTION_ERRORS:
            # Database availability is not an objective failure. run_forever
            # reopens its own connection resources and reclaims the checkpoint.
            raise
        except Exception as exc:
            await self._record_failure(run_id, phase, exc)
        finally:
            if services is not None and hasattr(services, "close"):
                try:
                    await services.close()
                except Exception as exc:
                    logger.error("Service cleanup failed (%s)", type(exc).__name__)

    async def _schedule_continuation(self, run, values, reason, delay, failures):
        projection = {key: values[key] for key in GRAPH_FIELDS if key in values}
        try:
            updated = await self.storage.schedule_retry(
                run["run_id"],
                self.worker_id,
                delay,
                reason,
                **projection,
                autonomous_failures=failures,
            )
        except ConflictError as exc:
            # A lost lease cannot authorize a stale worker to change the run.
            raise asyncio.CancelledError from exc
        await self.storage.emit(
            {
                "run_id": run["run_id"],
                "agent_id": "executive",
                "activity": "idle" if updated["status"] == "cancelled" else "waiting",
                "summary": "Automatic continuation queued"
                if updated["status"] == "queued"
                else f"Run {updated['status']}",
                "data": {
                    "next_attempt_at": updated.get("next_attempt_at"),
                    "reason": reason[:2000],
                },
            }
        )

    async def _record_failure(self, run_id, phase, exc):
        # Keep useful locations without provider bodies, source lines or inputs.
        failure_context = {
            "phase": phase,
            "type": type(exc).__name__,
            "frames": [
                {"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
                for frame in traceback.extract_tb(exc.__traceback__)[-12:]
            ],
        }
        logger.error("Run %s failed: %s", run_id, failure_context)
        await self.storage.update_run(
            run_id,
            status="failed",
            error=f"Execution failed during {phase} ({type(exc).__name__})",
            failure_context=failure_context,
        )
        await self.storage.emit(
            {
                "run_id": run_id,
                "agent_id": "executive",
                "activity": "error",
                "summary": f"Execution failed during {phase} ({type(exc).__name__})",
            }
        )

    async def run_forever(self) -> None:
        configure_tracing(self.settings)
        own_checkpointer, own_store = self.checkpointer is None, self.store is None
        failures = 0
        while True:
            stack = AsyncExitStack()
            try:
                await self.storage.open()
                try:
                    ready = await self.storage.ready(raise_errors=True)
                except UndefinedTable as exc:
                    raise RuntimeError("Database is not migrated; run spoc migrate") from exc
                if not ready:
                    raise RuntimeError("Database is not migrated; run spoc migrate")
                await self._open_runtime_resources(stack)
                if hasattr(self.storage, "register_runtime_resources"):
                    self.storage.register_runtime_resources(self.checkpointer, self.store)
                while True:
                    if not await self.run_once():
                        await asyncio.sleep(1)
                    failures = 0
            except CONNECTION_ERRORS as exc:
                failures += 1
                # Class names provide diagnostics without connection strings,
                # SQL parameters, provider bodies, or credentials.
                logger.warning("Worker database connection unavailable (%s)", type(exc).__name__)
            finally:
                try:
                    await stack.aclose()
                except CONNECTION_ERRORS as exc:
                    logger.warning("Database resource cleanup failed (%s)", type(exc).__name__)
                try:
                    await self.storage.close()
                except CONNECTION_ERRORS as exc:
                    logger.warning("Database pool cleanup failed (%s)", type(exc).__name__)
                if not isinstance(self.storage, MemoryStorage):
                    if own_checkpointer:
                        self.checkpointer = None
                    if own_store:
                        self.store = None
            if self._storage_factory is not None:
                self.storage = self._storage_factory()
            await asyncio.sleep(retry_delay(failures))

    async def _open_runtime_resources(self, stack: AsyncExitStack) -> None:
        if isinstance(self.storage, MemoryStorage):
            from langgraph.checkpoint.memory import InMemorySaver
            from langgraph.store.memory import InMemoryStore

            if self.checkpointer is None:
                self.checkpointer = InMemorySaver()
            if self.store is None:
                self.store = InMemoryStore()
        else:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from langgraph.store.postgres import AsyncPostgresStore

            url = self.settings.database_url.get_secret_value()
            if self.checkpointer is None:
                self.checkpointer = await stack.enter_async_context(
                    AsyncPostgresSaver.from_conn_string(url)
                )
            if self.store is None:
                self.store = await stack.enter_async_context(
                    AsyncPostgresStore.from_conn_string(url)
                )


async def run_worker(settings: Settings | None = None) -> None:
    await Worker(settings or Settings()).run_forever()
