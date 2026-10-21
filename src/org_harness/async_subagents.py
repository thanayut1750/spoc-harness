"""Durable, locally owned background delegations, independent of model history.

The mission Worker owns every asyncio task. Operation records and private agent
checkpoints survive that owner; Python tasks never outlive its service lifetime.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
from typing import Any, Literal

from langgraph.checkpoint.memory import InMemorySaver
from psycopg import InterfaceError, OperationalError
from psycopg_pool import PoolClosed, PoolTimeout

from org_harness.autonomy import AutonomousCheckpointYield, autonomous_mode
from org_harness.models import Constitution, EscalationSignal, KeyResult
from org_harness.storage import ConflictError, timestamp
from org_harness.tools import ExpectedToolInputError

Mode = Literal["auto", "research", "build_tool"]
TERMINAL = {"done", "error", "cancelled"}


def task_agent_id(run_id: str, task_id: str) -> str:
    return f"specialist:{run_id}:{hashlib.sha256(task_id.encode()).hexdigest()[:16]}"


class AsyncSubagentManager:
    def __init__(self, services: Any):
        self.services = services
        self.tasks: dict[str, asyncio.Task] = {}
        self.hosts: dict[str, Any] = {}
        self.lock = asyncio.Lock()
        self.slots = asyncio.Semaphore(2)
        self.closed = False

    def authorize(self, caller: str, host: Any, kr: KeyResult | None) -> None:
        if (
            caller not in {"planner", "engineering_head"}
            or host.role != caller
            or host.run.get("run_id") != self.services.run_id
        ):
            raise EscalationSignal("policy_violation", "This agent cannot manage background R&D")
        if host.kr_id != (kr.kr_id if kr else "planner") or host.version != (
            kr.version if kr else 1
        ):
            raise EscalationSignal("policy_violation", "Background R&D assignment does not match")

    def matches(self, operation: dict, caller: str, host: Any) -> bool:
        request = operation.get("request", {})
        return (
            operation.get("run_id") == self.services.run_id
            and operation.get("kind") == "async_subagent"
            and request.get("caller") == caller
            and request.get("parent_scope") == host.scope
            and request.get("kr_id") == host.kr_id
            and request.get("version") == host.version
            and request.get("epoch") == host.epoch
        )

    def public(self, operation: dict) -> dict:
        result = operation.get("result") or {}
        report = result.get("result") or {}
        return {
            "task_id": operation["operation_id"],
            "agent_name": "tools_rd_lead",
            "agent_id": task_agent_id(self.services.run_id, operation["operation_id"]),
            "parent_agent_id": operation["request"]["caller"],
            "parent_task_id": operation["request"].get("parent_task_id"),
            "execution_mode": "async",
            "kr_id": operation["request"]["kr_id"],
            "created_at": operation.get("created_at"),
            "updated_at": result.get("updated_at", operation.get("created_at")),
            "status": result.get("state", "queued"),
            **({"reason": str(result["reason"])[:1000]} if result.get("reason") else {}),
            **(
                {
                    "result": {
                        "mode": report.get("mode"),
                        "report": str(report.get("report", ""))[:2000],
                        "report_artifact_id": report.get("report_artifact_id"),
                        "artifact_ids": report.get("artifact_ids", [])[:8],
                        "artifact_count": len(report.get("artifact_ids", [])),
                        "tool_ids": [item.get("tool_id") for item in report.get("tools", [])][:8],
                        "tool_count": report.get("tool_count"),
                    }
                }
                if report
                else {}
            ),
        }

    async def reserve_consultation(
        self,
        caller: str,
        host: Any,
        call_id: str,
        requirement: str,
        mode: str,
        kr: KeyResult | None,
        *,
        kind: str,
    ) -> None:
        """One durable allowance shared by blocking and background delegations."""
        self.authorize(caller, host, kr)
        reservation_id = host.operation_id(call_id, f"rd_delegation:{kind}")
        request = {
            "caller": caller,
            "parent_scope": host.scope,
            "kr_id": host.kr_id,
            "version": host.version,
            "epoch": host.epoch,
            "requirement": requirement,
            "mode": mode,
        }
        async with self.lock:
            existing = await self.services.storage.get_operation(reservation_id)
            if existing is None and not autonomous_mode(self.services.limits):
                reservations = await self.services.storage.list_operations(
                    self.services.run_id, kind="rd_delegation"
                )
                count = sum(
                    item["request"].get("parent_scope") == host.scope
                    and item["request"].get("caller") == caller
                    and item["request"].get("kr_id") == host.kr_id
                    and item["request"].get("version") == host.version
                    and item["request"].get("epoch") == host.epoch
                    for item in reservations
                )
                if count >= 2:
                    raise ExpectedToolInputError(
                        "Tools R&D consultation limit reached; continue with existing evidence"
                    )
            try:
                await self.services.storage.begin_operation(
                    self.services.run_id, reservation_id, "rd_delegation", request
                )
            except ConflictError as exc:
                raise EscalationSignal(
                    "operation_conflict", "Background task request changed"
                ) from exc
            await self.services.storage.complete_operation(reservation_id, {"reserved": True})

    async def start(
        self,
        caller: str,
        host: Any,
        call_id: str,
        requirement: str,
        constitution: Constitution,
        kr: KeyResult | None = None,
        *,
        agent_name: str = "tools_rd_lead",
        mode: Mode = "auto",
    ) -> dict:
        self.authorize(caller, host, kr)
        if agent_name != "tools_rd_lead":
            raise ExpectedToolInputError("Only tools_rd_lead supports background delegation")
        if not requirement.strip() or mode not in {"auto", "research", "build_tool"}:
            raise ExpectedToolInputError(
                "Describe the R&D request and use auto, research or build_tool"
            )
        await self.reserve_consultation(caller, host, call_id, requirement, mode, kr, kind="async")
        task_id = host.operation_id(call_id, "async_rd")
        request = {
            "caller": caller,
            "parent_task_id": host.operation_id("session", caller),
            "parent_scope": host.scope,
            "kr_id": host.kr_id,
            "version": host.version,
            "epoch": host.epoch,
            "requirement": requirement,
            "mode": mode,
            "call_id": call_id,
            "constitution": constitution.model_dump(mode="json"),
            "kr": kr.model_dump(mode="json") if kr else None,
        }
        try:
            operation = await self.services.storage.begin_operation(
                self.services.run_id, task_id, "async_subagent", request
            )
        except ConflictError as exc:
            raise EscalationSignal("operation_conflict", "Background task request changed") from exc
        await self._schedule(operation, host)
        return self.public(operation)

    async def _schedule(self, operation: dict, host: Any) -> None:
        async with self.lock:
            task_id = operation["operation_id"]
            if self.closed:
                return
            if operation["status"] in TERMINAL:
                # A receipt can commit before its public event. Restoring it
                # repairs the projection without rerunning completed child work.
                await self._emit_lifecycle(operation)
                return
            if task_id in self.tasks and not self.tasks[task_id].done():
                return
            self.hosts[task_id] = host
            previous = operation.get("result") or {}
            host.command_operations.update(previous.get("command_operation_ids", []))
            await self._complete(task_id, {**previous, "state": "queued"}, status="pending")
            self.tasks[task_id] = asyncio.create_task(
                self._run(operation, host), context=contextvars.Context()
            )

    async def _emit_lifecycle(self, operation: dict) -> None:
        """Project persisted task facts, never private child messages or provider errors."""
        result = operation.get("result") or {}
        state = result.get("state", "queued")
        transitions = {
            "queued": ("waiting", "Background R&D queued"),
            "running": ("planning", "Background R&D starting"),
            "cancelled": ("idle", "Background R&D cancelled"),
            "failed": ("error", "Background R&D failed"),
            "succeeded": ("completed", "Background R&D completed"),
        }
        if state not in transitions:
            return
        activity, summary = transitions[state]
        if state == "cancelled" and result.get("reason") == "Superseded by replacement planning":
            summary = "Background R&D stopped: superseded by replacement planning"
        task_id = operation["operation_id"]
        request = operation["request"]
        actor = task_agent_id(self.services.run_id, task_id)
        self.services._dynamic_agents[actor] = {
            "display_name": f"Tools R&D: {request['requirement'][:60]}",
            "agent_type": "tools_rd_task",
            "parent_agent_id": request["caller"],
            "department": "engineering",
            "model_parent": "tools_rd_lead",
            "base_role": "tools_rd_lead",
            "task_id": task_id,
            "parent_task_id": request.get("parent_task_id"),
            "execution_mode": "async",
            "task_status": state,
        }
        await self.services.emit(
            actor,
            activity,
            summary,
            kr_id=request["kr_id"],
            task_id=task_id,
            task_status=state,
        )

    async def _complete(self, task_id: str, result: dict, status: str = "done") -> None:
        host = self.hosts.get(task_id)
        await self.services.storage.complete_operation(
            task_id,
            {
                **result,
                "updated_at": timestamp(),
                "command_operation_ids": sorted(host.command_operations)
                if host
                else result.get("command_operation_ids", []),
            },
            status,
        )
        operation = await self.services.storage.get_operation(task_id)
        assert operation is not None
        await self._emit_lifecycle(operation)

    async def restore(self, caller: str, host: Any, kr: KeyResult | None) -> None:
        self.authorize(caller, host, kr)
        for operation in await self.services.storage.list_operations(
            self.services.run_id, kind="async_subagent"
        ):
            if self.matches(operation, caller, host):
                await self._schedule(operation, host)
            elif (
                operation["status"] == "pending"
                and operation.get("request", {}).get("caller") == caller
                and operation["request"].get("kr_id") == host.kr_id
                and (operation["request"].get("version", 1), operation["request"].get("epoch", 0))
                <= (host.version, host.epoch)
            ):
                # A new canonical planning invocation supersedes old work for
                # this same caller/KR. Public tools still cannot cross scopes.
                task_id = operation["operation_id"]
                task = self.tasks.get(task_id)
                if task is not None:
                    if not task.done():
                        task.cancel()
                    results = await asyncio.gather(task, return_exceptions=True)
                    for result in results:
                        if isinstance(result, BaseException) and not isinstance(
                            result, asyncio.CancelledError
                        ):
                            raise result
                current = await self.services.storage.get_operation(task_id)
                if current["status"] != "pending":
                    continue
                host.command_operations.update(
                    (current.get("result") or {}).get("command_operation_ids", [])
                )
                await self._complete(
                    task_id,
                    {
                        "state": "cancelled",
                        "reason": "Superseded by replacement planning",
                        "command_operation_ids": (current.get("result") or {}).get(
                            "command_operation_ids", []
                        ),
                    },
                    "cancelled",
                )

    async def _run(self, operation: dict, host: Any) -> None:
        async with self.slots:
            await self._execute(operation, host)

    async def _execute(self, operation: dict, host: Any) -> None:
        task_id = operation["operation_id"]
        request = operation["request"]
        child = None
        actor = task_agent_id(self.services.run_id, task_id)
        try:
            await self._complete(task_id, {"state": "running"}, status="pending")
            current = await self.services.storage.get_run(self.services.run_id)
            if current.get("cancel_requested"):
                await self._complete(
                    task_id, {"state": "cancelled", "reason": "Mission cancelled"}, "cancelled"
                )
                return
            child = self.services._background_service(current)
            child._dynamic_agents[actor] = self.services._dynamic_agents[actor].copy()
            # The child graph has an independent, durable session even for a
            # finite parent; never change the parent graph's middleware topology.
            child.run["private_agent_sessions"] = True
            if self.services.agent_checkpointer is None:
                self.services.agent_checkpointer = InMemorySaver()
            child.agent_checkpointer = self.services.agent_checkpointer
            result = await child.consult_tools_rd(
                request["caller"],
                request["requirement"],
                Constitution.model_validate(request["constitution"]),
                host,
                request["call_id"],
                KeyResult.model_validate(request["kr"]) if request["kr"] else None,
                mode=request["mode"],
                actor_id=actor,
            )
            # Use the same authoritative public delegation format as the
            # blocking tool, without charging another dispatch or exposing chat.
            evidence = await self.services.artifacts.save(
                f"tools_rd_consultation-{task_id}.json",
                json.dumps(result),
                kr_id=host.kr_id,
                department=host.department,
                epoch=host.epoch,
                version=host.version,
                scope=host.scope,
                kind="research",
                write_id=host.operation_id(task_id, "async_rd_report"),
            )
            await self._complete(
                task_id,
                {
                    "state": "succeeded",
                    "result": result,
                    "consultation_artifact_id": evidence["artifact_id"],
                },
            )
        except AutonomousCheckpointYield as exc:
            await self._complete(
                task_id,
                {
                    "state": "queued",
                    "reason": exc.reason,
                    "delay_seconds": exc.delay_seconds,
                    "recoverable_failure": exc.recoverable_failure,
                },
                status="pending",
            )
        except asyncio.CancelledError:
            await self._complete(
                task_id,
                {"state": "queued", "reason": "Owner stopped; saved progress retained"},
                status="pending",
            )
            raise
        except EscalationSignal as exc:
            await self._complete(
                task_id, {"state": "failed", "kind": exc.kind, "reason": exc.reason}, "error"
            )
        except (OperationalError, InterfaceError, PoolTimeout, PoolClosed):
            # The Worker owns reconnect/lease loss. Do not turn a lost database
            # connection into a completed task or a model-repairable resource error.
            raise
        except Exception as exc:
            await self._complete(
                task_id,
                {
                    "state": "failed",
                    "kind": "internal_error",
                    "reason": f"Background R&D failed ({type(exc).__name__})",
                },
                "error",
            )
            raise
        finally:
            if child is not None:
                await child.close()

    async def _owned(self, caller: str, host: Any, kr: KeyResult | None, task_id: str) -> dict:
        self.authorize(caller, host, kr)
        operation = await self.services.storage.get_operation(task_id)
        if not operation or not self.matches(operation, caller, host):
            raise ExpectedToolInputError("Background task is outside this planning assignment")
        return operation

    async def check(self, caller: str, host: Any, kr: KeyResult | None, task_id: str) -> dict:
        operation = await self._owned(caller, host, kr, task_id)
        return self.public(operation)

    async def wait(
        self, caller: str, host: Any, kr: KeyResult | None, task_id: str, seconds: float = 30
    ) -> dict:
        await self._owned(caller, host, kr, task_id)
        if not 0 < seconds <= 30:
            raise ExpectedToolInputError("Wait between zero and 30 seconds")
        task = self.tasks.get(task_id)
        if task is not None:
            await asyncio.wait({task}, timeout=seconds)
            if task.done() and not task.cancelled():
                task.result()
        return await self.check(caller, host, kr, task_id)

    async def list_tasks(
        self, caller: str, host: Any, kr: KeyResult | None, *, offset: int = 0
    ) -> dict:
        self.authorize(caller, host, kr)
        if offset < 0:
            raise ExpectedToolInputError("Use offset >= 0")
        operations = [
            item
            for item in await self.services.storage.list_operations(
                self.services.run_id, kind="async_subagent"
            )
            if self.matches(item, caller, host)
        ]
        end = offset + 10
        return {
            "tasks": [self.public(item) for item in operations[offset:end]],
            "total": len(operations),
            "next_offset": end if end < len(operations) else None,
        }

    async def cancel(self, caller: str, host: Any, kr: KeyResult | None, task_id: str) -> dict:
        operation = await self._owned(caller, host, kr, task_id)
        if operation["status"] in TERMINAL:
            return self.public(operation)
        task = self.tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._complete(
            task_id, {"state": "cancelled", "reason": "Cancelled by requesting lead"}, "cancelled"
        )
        return await self.check(caller, host, kr, task_id)

    async def join(self, caller: str, host: Any, kr: KeyResult | None) -> list[dict]:
        self.authorize(caller, host, kr)
        operations = [
            item
            for item in await self.services.storage.list_operations(
                self.services.run_id, kind="async_subagent"
            )
            if self.matches(item, caller, host)
        ]
        tasks = [
            self.tasks[item["operation_id"]]
            for item in operations
            if item["operation_id"] in self.tasks and item["status"] != "cancelled"
        ]
        if tasks:
            await asyncio.gather(*tasks)
        for operation_id in host.command_operations:
            command = await self.services.storage.get_operation(operation_id)
            if command and command["kind"] == "command" and command["status"] == "pending":
                if autonomous_mode(self.services.limits):
                    raise AutonomousCheckpointYield(
                        "Interrupted background command requires receipt reconciliation"
                    )
                raise EscalationSignal(
                    "unknown_operation", f"Review interrupted background command {operation_id}"
                )
        for item in operations:
            current = await self.services.storage.get_operation(item["operation_id"])
            result = current.get("result") or {}
            if current["status"] == "pending":
                raise AutonomousCheckpointYield(
                    "Background R&D saved progress; continue its next work slice",
                    result.get("delay_seconds", 0),
                    recoverable_failure=result.get("recoverable_failure", False),
                )
            if result.get("kind") == "internal_error":
                raise RuntimeError(result.get("reason", "Background R&D failed internally"))
            if current["status"] == "error":
                raise EscalationSignal(
                    result.get("kind", "blocked"),
                    f"Background R&D {item['operation_id']}: {result.get('reason', 'did not complete')}",
                )
        return [
            self.public(await self.services.storage.get_operation(item["operation_id"]))
            for item in operations
        ]

    async def close(self) -> None:
        async with self.lock:
            self.closed = True
            tasks = list(self.tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
