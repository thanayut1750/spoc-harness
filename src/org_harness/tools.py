"""Host tools and artifact storage with replay-aware operation records."""

import asyncio
import hashlib
import json
import mimetypes
import os
import signal
import tempfile
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from org_harness.models import EscalationSignal
from org_harness.storage import ArtifactNotFoundError, BudgetExceeded, fingerprint
from org_harness.text_safety import contains_invalid_json_text


class ExpectedToolInputError(ValueError):
    """A known model-input/resource failure that is safe to return as a tool result."""


def json_safe_display(value: Any) -> Any:
    """Escape unsafe external text for display, preserving its reversible representation."""
    if not contains_invalid_json_text(value):
        return value
    return _escaped_display(value)


def _escaped_display(value: Any) -> Any:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)[1:-1]
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
        invalid_request = contains_invalid_json_text(request)
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
                    "Tool input contains null or invalid Unicode text. Use valid text inputs; "
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
        if contains_invalid_json_text(result):
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
            return {
                "path": str(target),
                "content": readable_text(body, partial=len(body) == 262148)[:65536],
            }

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
            log_id = self.operation_id(call_id, "run_command")
            log_dir = self.artifacts.root / "operations"
            log_dir.mkdir(parents=True, exist_ok=True)
            stdout_path, stderr_path = log_dir / f"{log_id}.stdout", log_dir / f"{log_id}.stderr"
            await self.emit(self.role, "executing", command[:160], kr_id=self.kr_id)
            cancelled, timed_out = False, False
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                try:
                    process = await asyncio.create_subprocess_exec(
                        "/bin/bash",
                        "-lc",
                        command,
                        cwd=str(working_directory),
                        stdout=stdout,
                        stderr=stderr,
                        start_new_session=True,
                    )
                except (OSError, ValueError) as exc:
                    raise ExpectedToolInputError(
                        f"Command process could not start ({type(exc).__name__})"
                    ) from exc
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
            if contains_invalid_json_text(result):
                result = {**json_safe_display(result), "display_encoding": "json-string-escape"}
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
            unsafe_source = contains_invalid_json_text(result)
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
