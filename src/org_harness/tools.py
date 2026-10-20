"""Host tools and artifact storage with replay-aware operation records."""

import asyncio
import hashlib
import json
import math
import mimetypes
import os
import signal
import sys
import tempfile
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from org_harness.autonomy import AutonomousCheckpointYield, autonomous_mode
from org_harness.command_runner import (
    atomic_json,
    process_identity,
    same_process,
    signal_process,
    stop_session_children,
)
from org_harness.models import EscalationSignal
from org_harness.storage import ArtifactNotFoundError, BudgetExceeded, fingerprint
from org_harness.text_safety import contains_invalid_json_text, contains_invalid_json_value

_COMMAND_PREVIEW_BYTES = 32768
_COMMAND_ARTIFACT_BYTES = 2_000_000
_RECOVERY_GUIDANCE = (
    "This receipt never authorizes replaying the interrupted command. Inspect existing files, "
    "logs, process state and external effects before deciding how to repair the assignment. "
    "Use fresh verification to establish acceptance criteria; an interrupted/unknown receipt "
    "is not successful evidence."
)


def _command_record(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _command_file_id(operation_id: str) -> str:
    return (
        operation_id
        if len(operation_id) == 64 and all(char in "0123456789abcdef" for char in operation_id)
        else hashlib.sha256(operation_id.encode()).hexdigest()
    )


def _verified_supervisor(manifest: dict, path: Path) -> bool:
    identity = manifest.get("process")
    if not isinstance(identity, dict) or not isinstance(identity.get("pid"), int):
        return False
    if identity.get("session") != identity["pid"] or identity.get("pgid") != identity["pid"]:
        return False
    if not same_process(identity, process_identity(identity["pid"])):
        return False
    try:
        args = Path(f"/proc/{identity['pid']}/cmdline").read_bytes().split(b"\x00")
        return (
            str(Path(__file__).with_name("command_runner.py")).encode() in args
            and str(path).encode() in args
            and manifest.get("token", "").encode() in args
            and bool(manifest.get("token"))
        )
    except (OSError, ValueError, AttributeError):
        return False


async def _stop_supervisor(manifest: dict, path: Path) -> bool:
    if not _verified_supervisor(manifest, path):
        return False
    identity = manifest["process"]
    signal_process(identity, signal.SIGTERM)
    deadline = asyncio.get_running_loop().time() + 3
    while asyncio.get_running_loop().time() < deadline:
        current = process_identity(identity["pid"])
        if not same_process(identity, current) or (current and current["state"] == "Z"):
            return True
        await asyncio.sleep(0.05)
    # A hung supervisor must not leave its command running. Clean its verified
    # private session before stopping the exact leader. Never kill a raw PID.
    if not _verified_supervisor(manifest, path):
        return False
    if not await asyncio.to_thread(stop_session_children, identity):
        return False
    signal_process(identity, signal.SIGKILL)
    deadline = asyncio.get_running_loop().time() + 1
    while asyncio.get_running_loop().time() < deadline:
        current = process_identity(identity["pid"])
        if not same_process(identity, current) or (current and current["state"] == "Z"):
            return True
        await asyncio.sleep(0.05)
    return False


async def _save_command_receipt(
    artifacts: "Artifacts", operation_id: str, context: dict, result: dict
) -> dict:
    log_dir = artifacts.root / "operations"
    file_id = _command_file_id(operation_id)
    saved = []
    metadata = {
        "kr_id": context.get("kr_id", ""),
        "department": context.get("department", ""),
        "epoch": context.get("epoch", 0),
        "version": context.get("version", 1),
        "scope": context.get("scope", ""),
        "exit_code": result["exit_code"],
        "command": context["command"],
        "cwd": context.get("cwd", ""),
        "operation_id": operation_id,
    }
    for suffix in ("stdout", "stderr"):
        path = log_dir / f"{file_id}.{suffix}"
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                body = handle.read(_COMMAND_ARTIFACT_BYTES)
        except FileNotFoundError:
            size = 0
            body = b""
        result[suffix] = body[:_COMMAND_PREVIEW_BYTES].decode(errors="replace")
        result[f"{suffix}_truncated"] = size > _COMMAND_PREVIEW_BYTES
        result[f"{suffix}_log_bytes"] = size
        result[f"{suffix}_artifact_truncated"] = size > len(body)
        if body:
            artifact = await artifacts.save(
                f"{file_id}.{suffix}.txt", body, kind="command_log", **metadata
            )
            saved.append(artifact["artifact_id"])
    unsafe_display = contains_invalid_json_value(result)
    result = {**json_safe_display(result), "artifact_ids": saved}
    if unsafe_display:
        result["display_encoding"] = "json-string-escape"
    receipt = await artifacts.save(
        f"{file_id}.command.json",
        json.dumps({"command": context["command"], "cwd": context.get("cwd", ""), **result}),
        kind="command_result",
        **metadata,
    )
    result["artifact_ids"] = [*saved, receipt["artifact_id"]]
    return result


def _durable_command_result(manifest: dict | None, path: Path) -> dict:
    terminal = _command_record(path.with_suffix(".result.json")) if manifest else None
    if (
        manifest
        and terminal
        and terminal.get("operation_id") == manifest.get("operation_id")
        and terminal.get("request_fingerprint") == manifest.get("request_fingerprint")
        and isinstance(terminal.get("exit_code"), int)
        and not isinstance(terminal["exit_code"], bool)
        and -255 <= terminal["exit_code"] <= 255
        and terminal.get("execution_stopped") is True
        and all(
            isinstance(terminal.get(key), bool)
            for key in ("timed_out", "interrupted", "effects_uncertain")
        )
        and isinstance(terminal.get("duration_seconds"), (int, float))
        and not isinstance(terminal["duration_seconds"], bool)
        and terminal["duration_seconds"] >= 0
        and not (
            terminal["exit_code"] == 0
            and any(terminal[key] for key in ("timed_out", "interrupted", "effects_uncertain"))
        )
        and not contains_invalid_json_value(terminal)
        and same_process(manifest.get("process", {}), terminal.get("process"))
    ):
        return {
            key: terminal[key]
            for key in (
                "exit_code",
                "timed_out",
                "interrupted",
                "effects_uncertain",
                "execution_stopped",
                "duration_seconds",
            )
        } | {"process_state": "stopped", "recovery_guidance": _RECOVERY_GUIDANCE}
    return {
        "exit_code": 125,
        "timed_out": False,
        "interrupted": True,
        "effects_uncertain": True,
        "execution_stopped": False,
        "duration_seconds": None,
        "process_state": "unverified",
        "recovery_guidance": _RECOVERY_GUIDANCE,
    }


async def reconcile_pending_commands(settings: Any, storage: Any, run: dict) -> list[dict]:
    """Finalize truthful recovery receipts, without ever replaying a command.

    The worker calls this under its exclusive lease. Legacy records have no
    trustworthy process identity: leave effects explicitly unverified and let
    the agent inspect them rather than signalling anything or assuming success.
    """
    if not autonomous_mode(run.get("limits")):
        return []
    artifacts = Artifacts(storage, settings.data_dir, run["run_id"])
    import fcntl

    results = []
    for operation in await storage.uncertain_operations(run["run_id"]):
        operation_id = operation["operation_id"]
        file_id = _command_file_id(operation_id)
        path = artifacts.root / "operations" / f"{file_id}.process.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        manifest = _command_record(path)
        request = operation.get("request", {})
        valid = bool(
            manifest
            and file_id == operation_id
            and manifest.get("run_id") == run["run_id"]
            and manifest.get("operation_id") == operation_id
            and manifest.get("request_fingerprint") == fingerprint(request)
            and manifest.get("command") == request.get("command")
        )
        if valid and manifest is not None and _verified_supervisor(manifest, path):
            if not await _stop_supervisor(manifest, path):
                raise AutonomousCheckpointYield("Waiting for interrupted command cleanup", 5)
        with path.with_suffix(".lock").open("ab") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AutonomousCheckpointYield(
                    "Waiting for interrupted command identity", 5
                ) from exc
            result = _durable_command_result(manifest if valid else None, path)
            context = (
                manifest
                if valid and manifest is not None
                else {
                    "command": str(request.get("command", "")),
                    "cwd": str(request.get("cwd") or run.get("workspace_path") or ""),
                }
            )
            result = await _save_command_receipt(artifacts, operation_id, context, result)
            await storage.complete_operation(operation_id, result)
            results.append({"operation_id": operation_id, "result": result})
    return results


async def stop_run_command_processes(settings: Any, run: dict) -> list[str]:
    """Stop verified managed supervisors before reset moves/deletes their records.

    The caller holds the exclusive worker lock. An unverified *locked* record
    remains intact until ownership can be established; an unrelated PID in an
    unlocked stale record is never signalled.
    """
    import fcntl

    root = Artifacts(None, settings.data_dir, run["run_id"]).root / "operations"
    if any(path.is_symlink() for path in (root.parent.parent, root.parent, root)):
        return []
    stopped = []
    for path in root.glob("*.process.json"):
        if path.is_symlink() or path.with_suffix(".lock").is_symlink():
            raise AutonomousCheckpointYield("Command records must be inspected before reset", 5)
        manifest = _command_record(path)
        if (
            manifest
            and manifest.get("run_id") == run["run_id"]
            and isinstance(manifest.get("operation_id"), str)
            and path.name == f"{_command_file_id(manifest['operation_id'])}.process.json"
            and _verified_supervisor(manifest, path)
        ):
            if not await _stop_supervisor(manifest, path):
                raise AutonomousCheckpointYield("Waiting for command cleanup before reset", 5)
            stopped.append(manifest["operation_id"])
        with path.with_suffix(".lock").open("ab") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AutonomousCheckpointYield(
                    "Command ownership is not yet safe to reset", 5
                ) from exc
    return stopped


class ExpectedToolInputError(ValueError):
    """A known model-input/resource failure that is safe to return as a tool result."""


def json_safe_display(value: Any) -> Any:
    """Escape external text and represent non-finite numbers explicitly as strings."""
    if not contains_invalid_json_value(value):
        return value
    return _escaped_display(value)


def _escaped_display(value: Any) -> Any:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)[1:-1]
    if isinstance(value, float) and not math.isfinite(value):
        return json.dumps(value)
    if isinstance(value, dict):
        return {_escaped_display(key): _escaped_display(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_escaped_display(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_escaped_display(item) for item in value)
    return value


def readable_text(body: bytes, *, partial: bool = False) -> str:
    """Accept UTF-8 text, never reinterpret binary bytes as model-readable content."""
    import codecs

    if body.startswith(
        (b"\x89PNG", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"%PDF-", b"PK\x03\x04")
    ):
        raise ExpectedToolInputError(
            "This is a binary file. Text tools cannot inspect images or other binary content. "
            "Use command verification for its type/size and reference its file path or artifact download."
        )
    try:
        content = codecs.getincrementaldecoder("utf-8-sig")().decode(body, final=not partial)
    except UnicodeError as exc:
        raise ExpectedToolInputError(
            "This file is not UTF-8 text. Use command verification or its artifact download; "
            "text tools cannot inspect binary/image content."
        ) from exc
    if contains_invalid_json_text(content):
        raise ExpectedToolInputError(
            "This file contains null or invalid text characters. Use command verification "
            "or its artifact download; read_file and read_artifact support text only."
        )
    return content


class ReferenceTextParser(HTMLParser):
    """Extract readable reference text without running page scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden.append(tag)
        if not self.hidden and tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.hidden and self.hidden[-1] == tag:
            self.hidden.pop()
        if not self.hidden and tag in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)

    def text(self) -> str:
        return "\n".join(
            line for part in "".join(self.parts).splitlines() if (line := " ".join(part.split()))
        )


async def read_reference_page(url: str) -> dict:
    """Fetch a bounded textual reference for engineering without an MCP entitlement."""
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ExpectedToolInputError("Reference URL is malformed") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ExpectedToolInputError(
            "Reference URL must use http:// or https:// and include a hostname"
        )
    max_bytes = 2_000_000
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, max_redirects=5) as client:
            async with client.stream(
                "GET",
                url,
                headers={
                    "User-Agent": "SPOC-Harness/0.1 (reference retrieval)",
                    "Accept": "text/html,application/xhtml+xml,text/plain",
                },
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type and not (
                    content_type.startswith("text/")
                    or content_type in {"application/xhtml+xml", "application/json"}
                ):
                    raise ExpectedToolInputError(
                        "Reference URL must return an HTML or textual page"
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > max_bytes:
                        raise ExpectedToolInputError(
                            "Reference page exceeds the 2000000-byte source limit"
                        )
                    body.extend(chunk)
                content = body.decode(response.encoding or "utf-8", errors="replace")
                if content_type in {"text/html", "application/xhtml+xml"} or (
                    not content_type and content.lstrip().lower().startswith(("<!doctype", "<html"))
                ):
                    parser = ReferenceTextParser()
                    parser.feed(content)
                    content = parser.text()
                if not content.strip():
                    raise ExpectedToolInputError("Reference page returned no readable text")
                return {
                    "requested_url": url,
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "transport": "direct_http",
                    "content_type": content_type,
                    "text": content,
                }
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        detail = f", HTTP {status}" if status is not None else ""
        raise ExpectedToolInputError(
            f"Reference page request failed ({type(exc).__name__}{detail})"
        ) from exc


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
        except ArtifactNotFoundError:
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
        try:
            metadata = await self.storage.get_artifact(artifact_id)
        except ArtifactNotFoundError as exc:
            raise ExpectedToolInputError(
                "Artifact ID was not found. Use the exact artifact_id returned by a tool "
                "or supplied in prior outputs. Read a URL with read_web_page(url=...)."
            ) from exc
        if metadata["run_id"] != self.run_id:
            raise ExpectedToolInputError("Artifact belongs to a different run")
        try:
            body = Path(metadata["path"]).read_bytes()
        except OSError as exc:
            raise ExpectedToolInputError(
                f"Stored artifact content cannot be read ({type(exc).__name__})"
            ) from exc
        if hashlib.sha256(body).hexdigest() != metadata["sha256"]:
            raise ExpectedToolInputError("Artifact content no longer matches its evidence record")
        excerpt = body if limit is None else body[:limit]
        return metadata, readable_text(excerpt, partial=len(excerpt) < len(body))


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
        self._operation_locks: dict[str, asyncio.Lock] = {}
        self.emit = emit
        configured = run.get("workspace_path")
        if configured:
            try:
                self.workspace = Path(configured).expanduser().resolve()
                if not self.workspace.is_dir():
                    raise ValueError("Workspace is not a directory")
            except (OSError, ValueError, RuntimeError) as exc:
                raise EscalationSignal(
                    "missing_resource",
                    "Configured workspace is unavailable; provide an existing directory.",
                ) from exc
        else:
            self.workspace = (
                artifacts.root.parent.parent / "workspaces" / run["run_id"] / kr_id / str(epoch)
            )
            self.workspace.mkdir(parents=True, exist_ok=True)

    def path(self, path: str) -> Path:
        try:
            value = Path(path).expanduser()
            return value.resolve() if value.is_absolute() else (self.workspace / value).resolve()
        except (OSError, ValueError, RuntimeError) as exc:
            raise ExpectedToolInputError(f"Invalid host path ({type(exc).__name__})") from exc

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
        async with self._operation_locks.setdefault(operation_id, asyncio.Lock()):
            return await self._journal(operation_id, name, request, execute, kind=kind)

    async def _journal(
        self,
        operation_id: str,
        name: str,
        request: dict,
        execute: Callable[[], Awaitable[dict]],
        *,
        kind: str,
    ) -> dict:
        invalid_request = contains_invalid_json_value(request)
        stored_request = (
            {"invalid_input": True, "request_fingerprint": fingerprint(request)}
            if invalid_request
            else request
        )
        existing = await self.storage.get_operation(operation_id)
        if existing and fingerprint(existing["request"]) != fingerprint(stored_request):
            raise EscalationSignal(
                "operation_conflict", "A reused tool-call ID contains a different request"
            )
        if existing and existing["status"] == "done":
            return existing["result"]
        if (
            existing
            and existing["status"] == "pending"
            and kind == "command"
            and not invalid_request
        ):
            raise EscalationSignal(
                "unknown_operation", f"Review interrupted command {operation_id}"
            )
        try:
            await self.storage.reserve_budget(self.run["run_id"], "tool")
        except BudgetExceeded as exc:
            raise EscalationSignal("limit_exceeded", str(exc)) from exc
        await self.storage.begin_operation(
            self.run["run_id"],
            operation_id,
            "invalid_input" if invalid_request else kind,
            stored_request,
        )
        current = await self.storage.get_run(self.run["run_id"])
        if current.get("cancel_requested"):
            raise EscalationSignal("cancelled", "Run was cancelled")
        if current.get("governance_halt"):
            raise EscalationSignal("suspended", "Execution suspended for constitution review")
        try:
            if invalid_request:
                raise ExpectedToolInputError(
                    "Tool input contains invalid JSON values. Use finite numbers and valid text; "
                    "binary/image files require command verification or artifact downloads."
                )
            result = await execute()
        except ExpectedToolInputError as exc:
            # Only failures classified at the input/resource boundary are safe to complete.
            result = {"error": type(exc).__name__, "detail": str(exc)[:1000]}
        except EscalationSignal as exc:
            if exc.kind == "cancelled":
                await self.storage.complete_operation(operation_id, {"cancelled": True})
            raise
        if contains_invalid_json_value(result):
            result = {**json_safe_display(result), "display_encoding": "json-string-escape"}
        await self.storage.complete_operation(operation_id, result)
        return result

    async def write_file(self, call_id: str, path: str, content: str) -> dict:
        async def execute() -> dict:
            target = self.path(path)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            except (OSError, ValueError) as exc:
                raise ExpectedToolInputError(
                    f"Host file cannot be written ({type(exc).__name__})"
                ) from exc
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

    async def publish_file(self, call_id: str, path: str) -> dict:
        """Register an existing text output without sending its contents through the model."""

        async def execute() -> dict:
            target = self.path(path)
            try:
                with target.open("rb") as source:
                    body = source.read(2_000_001)
            except (OSError, ValueError) as exc:
                raise ExpectedToolInputError(
                    f"Output file cannot be published ({type(exc).__name__})"
                ) from exc
            if len(body) > 2_000_000:
                raise ExpectedToolInputError(
                    "Output file exceeds the 2000000-byte publication limit"
                )
            if not readable_text(body).strip():
                raise ExpectedToolInputError(
                    "Output file is empty; publish a completed text output"
                )
            artifact = await self.artifacts.save(
                target.name,
                body,
                kr_id=self.kr_id,
                department=self.department,
                epoch=self.epoch,
                version=self.version,
                scope=self.scope,
                kind="source",
                write_id=self.operation_id(call_id, "publish_file"),
                original_path=str(target),
            )
            await self.emit(
                self.role,
                "writing",
                f"Published {target.name}",
                kr_id=self.kr_id,
                artifact_id=artifact["artifact_id"],
            )
            return {
                "artifact_id": artifact["artifact_id"],
                "path": str(target),
                "size": artifact["size"],
                "sha256": artifact["sha256"],
            }

        return await self.journal(call_id, "publish_file", {"path": path}, execute)

    async def read_file(self, call_id: str, path: str) -> dict:
        async def execute() -> dict:
            target = self.path(path)
            try:
                with target.open("rb") as source:
                    body = source.read(262148)
            except (OSError, ValueError) as exc:
                raise ExpectedToolInputError(
                    f"Host file cannot be read ({type(exc).__name__})"
                ) from exc
            content = readable_text(body, partial=len(body) == 262148)[:65536]
            await self.emit(self.role, "reading", f"Read {target.name}", kr_id=self.kr_id)
            return {"path": str(target), "content": content}

        return await self.journal(call_id, "read_file", {"path": path}, execute)

    async def run_command(
        self,
        call_id: str,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> dict:
        configured_timeout = self.run.get("limits", {}).get("command_timeout", 300)
        timeout = min(timeout if timeout is not None else configured_timeout, configured_timeout)

        async def execute() -> dict:
            if timeout < 1:
                raise ExpectedToolInputError("Command timeout must be positive")
            working_directory = self.path(cwd) if cwd else self.workspace
            if not working_directory.is_dir():
                raise ExpectedToolInputError("Command cwd must be an existing directory")
            if "\x00" in command:
                raise ExpectedToolInputError("Command cannot contain null bytes")
            return await self._run_supervised_command(
                call_id, command, working_directory, timeout, requested_cwd=cwd
            )

        result = await self.journal(
            call_id,
            "run_command",
            {"command": command, "cwd": cwd, "timeout": timeout},
            execute,
            kind="command",
        )
        if result.get("cancelled"):
            raise EscalationSignal("cancelled", "Run was cancelled during host execution")
        return result

    async def _run_supervised_command(
        self,
        call_id: str,
        command: str,
        working_directory: Path,
        timeout: int,
        *,
        requested_cwd: str | None,
    ) -> dict:
        if (
            sys.platform != "linux"
            or not hasattr(os, "pidfd_open")
            or not hasattr(signal, "pidfd_send_signal")
        ):
            raise ExpectedToolInputError("Verified command cleanup requires Linux pidfd support")
        import fcntl

        operation_id = self.operation_id(call_id, "run_command")
        directory = self.artifacts.root / "operations"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{operation_id}.process.json"

        def cleanup_wait(reason: str) -> None:
            if autonomous_mode(self.run.get("limits")):
                raise AutonomousCheckpointYield(reason, 5)
            raise EscalationSignal("unknown_operation", reason)

        prior = _command_record(path)
        if prior and _verified_supervisor(prior, path) and not await _stop_supervisor(prior, path):
            cleanup_wait("Waiting for the previous command to stop before an approved retry")
        manifest = {
            "schema_version": 1,
            "phase": "prepared",
            "run_id": self.run["run_id"],
            "operation_id": operation_id,
            "request_fingerprint": fingerprint(
                {"command": command, "cwd": requested_cwd, "timeout": timeout}
            ),
            "command": command,
            "cwd": str(working_directory),
            "timeout": timeout,
            "token": uuid4().hex,
            "kr_id": self.kr_id,
            "department": self.department,
            "epoch": self.epoch,
            "version": self.version,
            "scope": self.scope,
            "actor_id": self.role,
        }
        process = None
        spawn = None
        cancelled = False
        await self.emit(self.role, "executing", command[:160], kr_id=self.kr_id)

        async def finish(*, commit: bool, emit_event: bool = True) -> dict:
            nonlocal process
            if process is None and spawn is not None:
                process = await asyncio.shield(spawn)
            recorded = _command_record(path) or manifest
            if process is not None and process.returncode is None:
                if not isinstance(recorded.get("process"), dict):
                    # We still own the subprocess handle when cancellation
                    # beats supervisor initialization; its command line + token
                    # verify the identity before any signal is sent.
                    recorded = {**recorded, "process": process_identity(process.pid)}
                if not await _stop_supervisor(recorded, path):
                    actual = process_identity(process.pid)
                    if actual is not None and actual["state"] != "Z":
                        cleanup_wait("Waiting for interrupted command cleanup")
                await process.wait()
            recorded = _command_record(path) or recorded
            result = _durable_command_result(recorded, path)
            result["cancelled"] = cancelled
            result = await _save_command_receipt(self.artifacts, operation_id, manifest, result)
            if commit:
                await self.storage.complete_operation(operation_id, result)
            if emit_event:
                await self.emit(
                    self.role,
                    "executing",
                    "Command interrupted; inspect its saved receipt before repair"
                    if result["interrupted"]
                    else f"Command exited {result['exit_code']}",
                    kr_id=self.kr_id,
                    **result,
                )
            return result

        with path.with_suffix(".lock").open("ab") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                if autonomous_mode(self.run.get("limits")):
                    raise AutonomousCheckpointYield(
                        "Waiting for command operation ownership", 5
                    ) from exc
                raise EscalationSignal(
                    "unknown_operation", "Command ownership must be resolved before retrying"
                ) from exc
            atomic_json(path, manifest)
            with (
                (directory / f"{operation_id}.stdout").open("wb") as stdout,
                (directory / f"{operation_id}.stderr").open("wb") as stderr,
            ):
                try:
                    spawn = asyncio.create_task(
                        asyncio.create_subprocess_exec(
                            sys.executable,
                            str(Path(__file__).with_name("command_runner.py")),
                            str(path),
                            str(lock.fileno()),
                            manifest["token"],
                            stdout=stdout,
                            stderr=stderr,
                            start_new_session=True,
                            pass_fds=(lock.fileno(),),
                        )
                    )
                    process = await asyncio.shield(spawn)
                    while process.returncode is None:
                        current = await self.storage.get_run(self.run["run_id"])
                        cancelled = current.get("cancel_requested", False)
                        if cancelled:
                            break
                        try:
                            await asyncio.wait_for(process.wait(), timeout=0.25)
                        except TimeoutError:
                            pass
                    return await finish(commit=autonomous_mode(self.run.get("limits")))
                except BaseException:
                    cleanup = asyncio.create_task(
                        finish(commit=autonomous_mode(self.run.get("limits")), emit_event=False)
                    )
                    await asyncio.shield(cleanup)
                    raise

    async def record_research(
        self, call_id: str, name: str, request: dict, execute: Callable[[], Awaitable[dict]]
    ) -> dict:
        async def recorded() -> dict:
            result = await execute()
            artifact = await self.artifacts.save(
                f"{name}-{call_id}.json",
                json.dumps(result, ensure_ascii=True, default=str),
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
            unsafe_source = contains_invalid_json_value(result)
            display = json_safe_display(result)
            encoded = json.dumps(display, ensure_ascii=False, default=str)
            preview = (
                display
                if len(encoded) <= 12000
                else {
                    "preview": encoded[:12000],
                    "truncated": True,
                    "total_characters": len(encoded),
                    "read_more": "Use read_artifact with offset and limit for the full stored source.",
                }
            )
            return {
                "artifact_id": artifact["artifact_id"],
                "result": preview,
                **({"display_encoding": "json-string-escape"} if unsafe_source else {}),
            }

        return await self.journal(call_id, name, request, recorded)
