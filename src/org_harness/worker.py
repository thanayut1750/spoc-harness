"""Leased host worker with durable graph checkpoints and explicit recovery."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack, suppress
from uuid import uuid4

from org_harness.config import Settings, configure_tracing
from org_harness.storage import MemoryStorage, create_storage

logger = logging.getLogger(__name__)
STATUS_MAP = {"completed": "succeeded", "awaiting_review": "review"}


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
        self.worker_id = str(uuid4())
        self.services_factory = services_factory
        self.graph_factory = graph_factory
        self.checkpointer = checkpointer
        self.store = store

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
        try:
            uncertain = await self.storage.uncertain_operations(run_id)
            if uncertain:
                operation = uncertain[0]
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
            if self.services_factory is None:
                from org_harness.agent_services import AgentServices

                services = AgentServices(self.settings, self.storage, run)
            else:
                services = self.services_factory(self.settings, self.storage, run)
            graph = (self.graph_factory or build_graph)(
                services, checkpointer=self.checkpointer, store=self.store
            )
            config = runtime_config(run_id)
            snapshot = await graph.aget_state(config)
            interrupts = tuple(getattr(snapshot, "interrupts", ()))
            decision = run.get("resume_decision")
            graph_input: object
            if decision and interrupts:
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
                    "activity": "planning",
                    "summary": "Recovering execution" if snapshot.values else "Starting execution",
                }
            )
            async for values in graph.astream(graph_input, config, stream_mode="values"):
                projection = {
                    key: values[key]
                    for key in (
                        "objectives",
                        "progress",
                        "outcomes",
                        "epochs",
                        "report",
                        "attempt_history",
                        "auto_replans",
                    )
                    if key in values
                }
                if projection:
                    await self.storage.update_run(run_id, **projection)
            snapshot = await graph.aget_state(config)
            values = dict(snapshot.values)
            fields = {
                key: values[key]
                for key in (
                    "objectives",
                    "progress",
                    "outcomes",
                    "report",
                    "review",
                    "epochs",
                    "attempt_history",
                    "auto_replans",
                )
                if key in values
            }
            interrupts = tuple(getattr(snapshot, "interrupts", ()))
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
                    "activity": "completed" if result["status"] == "succeeded" else "waiting",
                    "summary": f"Run {result['status']}",
                }
            )
        except asyncio.CancelledError:
            current = await self.storage.get_run(run_id)
            if current.get("cancel_requested"):
                await self.storage.update_run(run_id, status="cancelled")
            else:
                # Retain running state for checkpoint recovery after shutdown/lost lease.
                logger.info("Execution interrupted; checkpoint recovery remains available")
                raise
        except Exception as exc:
            logger.error("Run %s failed (%s)", run_id, type(exc).__name__)
            await self.storage.update_run(
                run_id, status="failed", error=f"Execution failed ({type(exc).__name__})"
            )
            await self.storage.emit(
                {
                    "run_id": run_id,
                    "agent_id": "executive",
                    "activity": "error",
                    "summary": f"Execution failed ({type(exc).__name__})",
                }
            )
        finally:
            if services is not None and hasattr(services, "close"):
                try:
                    await services.close()
                except Exception as exc:
                    logger.error("Service cleanup failed (%s)", type(exc).__name__)

    async def run_forever(self) -> None:
        configure_tracing(self.settings)
        await self.storage.open()
        try:
            if not await self.storage.ready():
                raise RuntimeError("Database unavailable or not migrated; run spoc migrate")
            async with AsyncExitStack() as stack:
                if self.checkpointer is None:
                    if isinstance(self.storage, MemoryStorage):
                        from langgraph.checkpoint.memory import InMemorySaver
                        from langgraph.store.memory import InMemoryStore

                        self.checkpointer, self.store = InMemorySaver(), InMemoryStore()
                    else:
                        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
                        from langgraph.store.postgres import AsyncPostgresStore

                        url = self.settings.database_url.get_secret_value()
                        self.checkpointer = await stack.enter_async_context(
                            AsyncPostgresSaver.from_conn_string(url)
                        )
                        self.store = await stack.enter_async_context(
                            AsyncPostgresStore.from_conn_string(url)
                        )
                while True:
                    if not await self.run_once():
                        await asyncio.sleep(1)
        finally:
            await self.storage.close()


async def run_worker(settings: Settings | None = None) -> None:
    await Worker(settings or Settings()).run_forever()
