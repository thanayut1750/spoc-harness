"""Host tools and artifact storage with replay-aware operation records."""

import asyncio
import hashlib
import json
import mimetypes
import os
import signal
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from org_harness.models import EscalationSignal
from org_harness.storage import BudgetExceeded, NotFoundError, fingerprint


class Artifacts:
    def __init__(self, storage: Any, data_dir: Path, run_id: str):
        self.storage = storage
        self.root = data_dir.resolve() / "artifacts" / run_id
        self.run_id = run_id

    async def save(
        self,
        name: str,
        content: str | bytes,
        *,
        kr_id: str = "",
        department: str = "",
        epoch: int = 0,
        version: int = 1,
        kind: str = "document",
        scope: str = "",
        write_id: str = "",
        **extra: Any,
    ) -> dict:
        body = content.encode() if isinstance(content, str) else content
        digest = hashlib.sha256(body).hexdigest()
        artifact_id = hashlib.sha256(
            json.dumps(
                [self.run_id, kr_id, version, department, epoch, scope, name, digest]
                + ([write_id] if write_id else [])
            ).encode()
        ).hexdigest()[:32]
        try:
            return await self.storage.get_artifact(artifact_id)
        except NotFoundError:
            pass
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / artifact_id
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(body)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        metadata = {
            "artifact_id": artifact_id,
            "run_id": self.run_id,
            "kr_id": kr_id,
            "department": department,
            "epoch": epoch,
            "version": version,
            "name": name,
            "path": str(path),
            "size": len(body),
            "sha256": digest,
            "kind": kind,
            "scope": scope,
            "write_id": write_id,
            "media_type": mimetypes.guess_type(name)[0] or "text/plain",
            **extra,
        }
        return await self.storage.register_artifact(metadata)

    async def read(self, artifact_id: str, *, limit: int | None = 65536) -> tuple[dict, str]:
        metadata = await self.storage.get_artifact(artifact_id)
        if metadata["run_id"] != self.run_id:
            raise ValueError("Artifact belongs to a different run")
        body = Path(metadata["path"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != metadata["sha256"]:
            raise ValueError("Artifact content no longer matches its evidence record")
        excerpt = body if limit is None else body[:limit]
        return metadata, excerpt.decode(errors="replace")


class HostTools:
    def __init__(
        self,
        storage: Any,
        artifacts: Artifacts,
        run: dict,
        *,
        kr_id: str,
        department: str,
        epoch: int,
        role: str,
        emit: Callable[..., Awaitable[None]],
        version: int = 1,
        work_package_id: str = "",
        attempt: int = 0,
    ):
        self.storage, self.artifacts, self.run = storage, artifacts, run
        self.kr_id, self.department, self.epoch, self.role = kr_id, department, epoch, role
        self.version = version
        self.scope = json.dumps([work_package_id or role, attempt, role])
        self.emit = emit
        configured = run.get("workspace_path")
        self.workspace = (
            Path(configured).expanduser().resolve()
            if configured
            else artifacts.root.parent.parent / "workspaces" / run["run_id"] / kr_id / str(epoch)
        )
        self.workspace.mkdir(parents=True, exist_ok=True)

    def path(self, path: str) -> Path:
        value = Path(path).expanduser()
        return value.resolve() if value.is_absolute() else (self.workspace / value).resolve()

    def operation_id(self, call_id: str, name: str) -> str:
        identity = [
            self.run["run_id"],
            self.kr_id,
            self.version,
            self.epoch,
            self.scope,
            call_id,
            name,
        ]
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    async def recorded_artifacts(self, *, current: bool = False) -> list[dict]:
        """Recover this exact assignment's evidence, including after checkpoint replay."""
        recorded = [
            item
            for item in await self.storage.list_artifacts(self.run["run_id"])
            if item.get("kr_id") == self.kr_id
            and item.get("version", 1) == self.version
            and item.get("epoch", 0) == self.epoch
            and item.get("scope") == self.scope
            and item.get("kind") != "deliverable"
        ]
        recorded.sort(key=lambda item: (item.get("created_at", ""), item["artifact_id"]))
        if not current:
            return recorded
        # Immutable snapshots remain inspectable, but an earlier broken file or
        # failed check must not override its corrected, later version.
        sources: dict[str, str] = {}
        commands: dict[tuple[str, str], str] = {}
        checks: dict[tuple[str, str], str] = {}
        for item in recorded:
            if item.get("kind") == "source":
                sources[item.get("original_path", item["name"])] = item["artifact_id"]
            elif item.get("kind") == "command_result":
                commands[(item.get("command", ""), item.get("cwd", ""))] = item.get(
                    "operation_id", ""
                )
            elif item.get("kind") == "verification":
                checks[(item.get("verification_tool", ""), item.get("original_path", ""))] = item[
                    "artifact_id"
                ]
        return [
            item
            for item in recorded
            if (
                item.get("kind") != "source"
                or sources[item.get("original_path", item["name"])] == item["artifact_id"]
            )
            and (
                item.get("kind") not in {"command_log", "command_result"}
                or item.get("operation_id")
                == commands.get((item.get("command", ""), item.get("cwd", "")))
            )
            and (
                item.get("kind") != "verification"
                or checks[(item.get("verification_tool", ""), item.get("original_path", ""))]
                == item["artifact_id"]
            )
        ]

    async def journal(
        self,
        call_id: str,
        name: str,
        request: dict,
        execute: Callable[[], Awaitable[dict]],
        *,
        kind: str = "tool",
    ) -> dict:
        operation_id = self.operation_id(call_id, name)
        existing = await self.storage.get_operation(operation_id)
        if existing and fingerprint(existing["request"]) != fingerprint(request):
            raise EscalationSignal(
                "operation_conflict", "A reused tool-call ID contains a different request"
            )
        if existing and existing["status"] == "done":
            return existing["result"]
        if existing and existing["status"] == "pending" and kind == "command":
            raise EscalationSignal(
                "unknown_operation", f"Review interrupted command {operation_id}"
            )
        try:
            await self.storage.reserve_budget(self.run["run_id"], "tool")
        except BudgetExceeded as exc:
            raise EscalationSignal("limit_exceeded", str(exc)) from exc
        await self.storage.begin_operation(self.run["run_id"], operation_id, kind, request)
        current = await self.storage.get_run(self.run["run_id"])
        if current.get("cancel_requested"):
            raise EscalationSignal("cancelled", "Run was cancelled")
        if current.get("governance_halt"):
            raise EscalationSignal("suspended", "Execution suspended for constitution review")
        try:
            result = await execute()
        except (OSError, ValueError) as exc:
            # A known pre-execution failure is complete, not an unknown command outcome.
            result = {"error": type(exc).__name__, "detail": str(exc)[:1000]}
        except EscalationSignal as exc:
            if exc.kind == "cancelled":
                await self.storage.complete_operation(operation_id, {"cancelled": True})
            raise
        await self.storage.complete_operation(operation_id, result)
        return result

    async def write_file(self, call_id: str, path: str, content: str) -> dict:
        async def execute() -> dict:
            target = self.path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            artifact = await self.artifacts.save(
                target.name,
                content,
                kr_id=self.kr_id,
                department=self.department,
                epoch=self.epoch,
                version=self.version,
                scope=self.scope,
                kind="source",
                write_id=self.operation_id(call_id, "write_file"),
                original_path=str(target),
            )
            await self.emit(
                self.role,
                "writing",
                f"Wrote {target.name}",
                kr_id=self.kr_id,
                artifact_id=artifact["artifact_id"],
            )
            return {"path": str(target), "artifact_id": artifact["artifact_id"]}

        return await self.journal(
            call_id, "write_file", {"path": path, "content": content}, execute
        )

    async def read_file(self, call_id: str, path: str) -> dict:
        async def execute() -> dict:
            target = self.path(path)
            return {"path": str(target), "content": target.read_text(errors="replace")[:65536]}

        return await self.journal(call_id, "read_file", {"path": path}, execute)

    async def run_command(
        self,
        call_id: str,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> dict:
        timeout = min(
            timeout or self.run.get("limits", {}).get("command_timeout", 300),
            self.run.get("limits", {}).get("command_timeout", 300),
        )
        if timeout < 1:
            raise ValueError("Command timeout must be positive")

        async def execute() -> dict:
            log_id = self.operation_id(call_id, "run_command")
            log_dir = self.artifacts.root / "operations"
            log_dir.mkdir(parents=True, exist_ok=True)
            stdout_path, stderr_path = log_dir / f"{log_id}.stdout", log_dir / f"{log_id}.stderr"
            await self.emit(self.role, "executing", command[:160], kr_id=self.kr_id)
            cancelled, timed_out = False, False
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = await asyncio.create_subprocess_exec(
                    "/bin/bash",
                    "-lc",
                    command,
                    cwd=str(self.path(cwd) if cwd else self.workspace),
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                started = asyncio.get_running_loop().time()
                try:
                    while process.returncode is None:
                        current = await self.storage.get_run(self.run["run_id"])
                        cancelled = current.get("cancel_requested", False)
                        timed_out = asyncio.get_running_loop().time() - started >= timeout
                        if cancelled or timed_out:
                            await self._terminate(process)
                            break
                        try:
                            await asyncio.wait_for(process.wait(), timeout=0.25)
                        except TimeoutError:
                            pass
                except BaseException:
                    await self._terminate(process)
                    raise
            elapsed = asyncio.get_running_loop().time() - started
            output_artifacts = []
            for suffix, log_path in (("stdout", stdout_path), ("stderr", stderr_path)):
                if not log_path.stat().st_size:
                    continue
                artifact = await self.artifacts.save(
                    f"{log_id}.{suffix}.txt",
                    log_path.read_bytes(),
                    kr_id=self.kr_id,
                    department=self.department,
                    epoch=self.epoch,
                    version=self.version,
                    scope=self.scope,
                    kind="command_log",
                    exit_code=124 if timed_out else process.returncode,
                    command=command,
                    cwd=str(self.workspace if not cwd else self.path(cwd)),
                    operation_id=log_id,
                )
                output_artifacts.append(artifact["artifact_id"])
            result = {
                "exit_code": 124 if timed_out else process.returncode,
                "stdout": stdout_path.read_bytes()[:32768].decode(errors="replace"),
                "stderr": stderr_path.read_bytes()[:32768].decode(errors="replace"),
                "timed_out": timed_out,
                "cancelled": cancelled,
                "duration_seconds": round(elapsed, 3),
                "artifact_ids": output_artifacts,
            }
            receipt = await self.artifacts.save(
                f"{log_id}.command.json",
                json.dumps(
                    {
                        "command": command,
                        "cwd": str(self.workspace if not cwd else self.path(cwd)),
                        **result,
                    }
                ),
                kr_id=self.kr_id,
                department=self.department,
                epoch=self.epoch,
                version=self.version,
                scope=self.scope,
                kind="command_result",
                exit_code=result["exit_code"],
                command=command,
                cwd=str(self.workspace if not cwd else self.path(cwd)),
                operation_id=log_id,
            )
            # Keep a receipt even for successful silent commands. Empty stdout
            # and stderr remain raw operation logs rather than empty task files.
            result["artifact_ids"] = [*output_artifacts, receipt["artifact_id"]]
            await self.emit(
                self.role,
                "executing",
                f"Command exited {result['exit_code']}",
                kr_id=self.kr_id,
                **result,
            )
            if cancelled:
                raise EscalationSignal("cancelled", "Run was cancelled during host execution")
            return result

        return await self.journal(
            call_id,
            "run_command",
            {"command": command, "cwd": cwd, "timeout": timeout},
            execute,
            kind="command",
        )

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), 1)
            except TimeoutError:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        except ProcessLookupError:
            await process.wait()

    async def record_research(
        self, call_id: str, name: str, request: dict, execute: Callable[[], Awaitable[dict]]
    ) -> dict:
        async def recorded() -> dict:
            result = await execute()
            artifact = await self.artifacts.save(
                f"{name}-{call_id}.json",
                json.dumps(result, ensure_ascii=False, default=str),
                kr_id=self.kr_id,
                department=self.department,
                epoch=self.epoch,
                version=self.version,
                scope=self.scope,
                kind="verification" if name == "syntax_check" else "research",
                **(
                    {
                        "verification_tool": name,
                        "original_path": str(self.path(result["path"])),
                        "passed": result.get("passed", False),
                    }
                    if name == "syntax_check"
                    else {}
                ),
            )
            await self.emit(
                self.role,
                "reading",
                f"Retrieved {name}",
                kr_id=self.kr_id,
                artifact_id=artifact["artifact_id"],
            )
            encoded = json.dumps(result, ensure_ascii=False, default=str)
            preview = (
                result
                if len(encoded) <= 12000
                else {
                    "preview": encoded[:12000],
                    "truncated": True,
                    "total_characters": len(encoded),
                    "read_more": "Use read_artifact with offset and limit for the full stored source.",
                }
            )
            return {"artifact_id": artifact["artifact_id"], "result": preview}

        return await self.journal(call_id, name, request, recorded)
