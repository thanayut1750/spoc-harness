"""Mission-scoped, tested scripts; generated code runs only as a journaled subprocess."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import re
import shlex
import sys
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from org_harness.autonomy import autonomous_mode
from org_harness.models import EscalationSignal
from org_harness.text_safety import contains_invalid_json_text
from org_harness.tools import Artifacts, ExpectedToolInputError, HostTools, readable_text

MAX_MISSION_TOOLS = 12
CATALOG_PAGE_BYTES = 32768


def bounded_json(value: Any, *, limit: int = 32768) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ExpectedToolInputError("Tool arguments must be finite JSON values") from exc
    if len(encoded) > limit or contains_invalid_json_text(value):
        raise ExpectedToolInputError("Tool JSON is oversized or contains unsupported text")
    return encoded


def validate_arguments(schema: dict, arguments: dict) -> None:
    bounded_json(schema, limit=8192)
    bounded_json(arguments)
    if schema.get("type") != "object":
        raise ExpectedToolInputError("Tool input_schema must describe an object")
    pending: list[tuple[Any, int]] = [(schema, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 16:
            raise ExpectedToolInputError("Tool schema is nested too deeply")
        if isinstance(item, dict):
            if any(key in item for key in ("$ref", "$dynamicRef", "$recursiveRef")):
                raise ExpectedToolInputError(
                    "Tool schemas must be self-contained without references"
                )
            pending.extend((value, depth + 1) for value in item.values())
        elif isinstance(item, list):
            pending.extend((value, depth + 1) for value in item)
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(arguments)
    except (SchemaError, ValidationError) as exc:
        # Validation messages can echo arguments and private source material.
        raise ExpectedToolInputError(
            "Arguments or input_schema failed JSON schema validation"
        ) from exc


def json_output(stdout: str) -> Any:
    def invalid_constant(_: str) -> None:
        raise ValueError("Non-finite JSON")

    try:
        output = json.loads(stdout, parse_constant=invalid_constant)
        bounded_json(output)
        return output
    except (ValueError, RecursionError) as exc:
        raise ExpectedToolInputError(
            "Mission tool must write one bounded JSON value to stdout"
        ) from exc


class MissionToolCatalog:
    def __init__(self, settings: Any, storage: Any, run: dict, artifacts: Artifacts):
        self.storage, self.run, self.artifacts = storage, run, artifacts
        self._registration_lock = asyncio.Lock()

    async def list_tools(self) -> list[dict]:
        """Descriptions are discovery data; invocation verifies the immutable evidence."""
        result = []
        artifacts = sorted(
            await self.storage.list_artifacts(self.run["run_id"]),
            key=lambda item: (item.get("created_at", ""), item["artifact_id"]),
        )
        for artifact in artifacts:
            if artifact.get("kind") != "mission_tool_definition":
                continue
            definition = artifact.get("tool_definition")
            if isinstance(definition, dict) and definition.get("tool_id"):
                result.append({**definition, "definition_artifact_id": artifact["artifact_id"]})
        return result

    async def preview(self) -> dict:
        """A fixed-size recent index, not execution evidence or a full schema."""
        tools = await self.list_tools()
        return {
            "tools": [
                {
                    "tool_id": item["tool_id"],
                    "name": item.get("name", ""),
                    "description": str(item.get("description", ""))[:240],
                }
                for item in reversed(tools[-3:])
            ],
            "total": len(tools),
            "has_more": len(tools) > 3,
            "discovery_only": True,
        }

    async def discover_tools(self, *, query: str = "", offset: int = 0, limit: int = 5) -> dict:
        """Page complete definitions in creation order, preserving every old version.

        New registrations append to the index rather than shifting older pages.
        Search matches IDs, names and descriptions; a byte limit can shorten a
        page before its requested count without truncating any JSON schema.
        """
        if (
            not isinstance(query, str)
            or len(query) > 256
            or contains_invalid_json_text(query)
            or type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= 5
        ):
            raise ExpectedToolInputError(
                "Catalog query must be at most 256 characters; offset must be nonnegative and limit 1–5"
            )
        search = query.casefold().strip()
        tools = [
            item
            for item in await self.list_tools()
            if not search
            or any(
                search in str(item.get(key, "")).casefold()
                for key in ("tool_id", "name", "description")
            )
        ]
        selected: list[dict] = []
        result = {
            "tools": selected,
            "total": len(tools),
            "offset": offset,
            "limit": limit,
            "has_more": False,
            "next_offset": None,
            "discovery_only": True,
        }
        for item in tools[offset : offset + limit]:
            next_offset = offset + len(selected) + 1
            has_more = next_offset < len(tools)
            candidate = {
                **result,
                "tools": [*selected, item],
                "has_more": has_more,
                "next_offset": next_offset if has_more else None,
            }
            if len(json.dumps(candidate, ensure_ascii=True, allow_nan=False)) > CATALOG_PAGE_BYTES:
                if not selected:
                    raise ExpectedToolInputError(
                        "Registered tool definition exceeds the discovery page limit"
                    )
                break
            selected.append(item)
        result["has_more"] = offset + len(selected) < len(tools)
        result["next_offset"] = offset + len(selected) if result["has_more"] else None
        return result

    def _authorize_host(self, host: HostTools) -> None:
        if host.run["run_id"] != self.run["run_id"] or host.artifacts.run_id != self.run["run_id"]:
            raise EscalationSignal("policy_violation", "Mission tool access belongs to another run")

    async def _run(self, host: HostTools, call_id: str, source: str, arguments: dict) -> dict:
        digest = hashlib.sha256(source.encode()).hexdigest()
        directory = host.workspace / ".mission-tools" / digest
        script = directory / "tool.py"
        input_path = directory / f"{host.operation_id(call_id, 'mission-input')}.json"
        encoded = bounded_json(arguments)
        for suffix, path, content in (
            ("source", script, source),
            ("input", input_path, encoded),
        ):

            async def materialize(path=path, content=content, suffix=suffix) -> dict:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
                except OSError as exc:
                    raise ExpectedToolInputError(
                        "Mission tool files could not be materialized"
                    ) from exc
                artifact = await self.artifacts.save(
                    path.name,
                    content,
                    kind="mission_tool_support",
                    kr_id=host.kr_id,
                    department=host.department,
                    epoch=host.epoch,
                    version=host.version,
                    scope=host.scope,
                    write_id=host.operation_id(f"{call_id}:{suffix}", "materialize_mission_tool"),
                )
                return {"path": str(path), "artifact_id": artifact["artifact_id"]}

            saved = await host.journal(
                f"{call_id}:{suffix}",
                "materialize_mission_tool",
                {"path": str(path), "sha256": hashlib.sha256(content.encode()).hexdigest()},
                materialize,
            )
            if saved.get("error"):
                raise ExpectedToolInputError("Mission tool files could not be materialized")
            try:
                intact = path.read_bytes() == content.encode()
            except OSError as exc:
                raise ExpectedToolInputError("Mission tool files are unavailable") from exc
            if not intact:
                raise ExpectedToolInputError(
                    "Mission tool materialization changed; no command executed"
                )
        command = (
            f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} "
            f"< {shlex.quote(str(input_path))}"
        )
        receipt = await host.run_command(f"{call_id}:execute", command, timeout=20)
        if receipt.get("error") or receipt.get("exit_code") != 0:
            raise ExpectedToolInputError(
                "Mission tool execution failed; inspect the recorded command evidence"
            )
        if receipt.get("stdout_truncated"):
            raise ExpectedToolInputError(
                "Mission tool JSON output exceeds the bounded output limit"
            )
        return {"output": json_output(receipt.get("stdout", "")), "receipt": receipt}

    async def register(
        self,
        host: HostTools,
        call_id: str,
        *,
        name: str,
        description: str,
        source_path: str,
        input_schema: dict,
        example_arguments: dict,
    ) -> dict:
        self._authorize_host(host)
        if host.role != "tools_rd_lead":
            raise EscalationSignal(
                "policy_violation", "Only Tools R&D lead can register mission tools"
            )

        async def create() -> dict:
            async with self._registration_lock:
                validate_arguments(input_schema, example_arguments)
                if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
                    raise ExpectedToolInputError("Tool name must be a short lowercase identifier")
                if not description.strip() or len(description) > 2000:
                    raise ExpectedToolInputError("Tool description must contain 1–2000 characters")
                current_run = await self.storage.get_run(self.run["run_id"])
                if (
                    not autonomous_mode(current_run.get("limits", {}))
                    and len(await self.list_tools()) >= MAX_MISSION_TOOLS
                ):
                    raise ExpectedToolInputError(
                        "This mission has reached its registered-tool limit"
                    )
                path = host.path(source_path)
                if not path.is_relative_to(host.workspace.resolve()) or path.suffix != ".py":
                    raise ExpectedToolInputError(
                        "Tool source must be a Python file inside the R&D workspace"
                    )
                try:
                    with path.open("rb") as handle:
                        body = handle.read(200001)
                except OSError as exc:
                    raise ExpectedToolInputError("Tool source file could not be read") from exc
                if not body.strip() or len(body) > 200000:
                    raise ExpectedToolInputError(
                        "Tool source must be nonempty and at most 200000 bytes"
                    )
                source = readable_text(body)
                try:
                    ast.parse(source)
                except (SyntaxError, ValueError, RecursionError) as exc:
                    raise ExpectedToolInputError("Tool source is not valid Python") from exc
                evidence = await self._run(host, f"{call_id}:smoke", source, example_arguments)
                source_artifact = await self.artifacts.save(
                    f"{name}.py",
                    source,
                    kind="mission_tool_source",
                    kr_id=host.kr_id,
                    department="engineering",
                    scope=host.scope,
                    epoch=host.epoch,
                    version=host.version,
                )
                definition = {
                    "tool_id": "tool:"
                    + hashlib.sha256(
                        bounded_json(
                            [
                                self.run["run_id"],
                                host.operation_id(call_id, "register_mission_tool"),
                                name,
                                source,
                                input_schema,
                            ],
                            limit=300000,
                        ).encode()
                    ).hexdigest()[:32],
                    "run_id": self.run["run_id"],
                    "name": name,
                    "description": description,
                    "input_schema": input_schema,
                    "source_artifact_id": source_artifact["artifact_id"],
                    "source_sha256": source_artifact["sha256"],
                    "test_artifact_ids": evidence["receipt"]["artifact_ids"],
                    "created_by": "tools_rd_lead",
                }
                artifact = await self.artifacts.save(
                    f"{name}.tool.json",
                    bounded_json(definition),
                    kind="mission_tool_definition",
                    kr_id=host.kr_id,
                    department="engineering",
                    scope=host.scope,
                    epoch=host.epoch,
                    version=host.version,
                    tool_definition=definition,
                )
                return {
                    **definition,
                    "definition_artifact_id": artifact["artifact_id"],
                    "artifact_ids": [
                        artifact["artifact_id"],
                        source_artifact["artifact_id"],
                        *evidence["receipt"]["artifact_ids"],
                    ],
                    "smoke_test_passed": True,
                }

        return await host.journal(
            call_id,
            "register_mission_tool",
            {
                "name": name,
                "description": description,
                "source_path": source_path,
                "input_schema": input_schema,
                "example_arguments": example_arguments,
            },
            create,
        )

    async def invoke(self, host: HostTools, call_id: str, *, tool_id: str, arguments: dict) -> dict:
        self._authorize_host(host)

        async def execute() -> dict:
            entries = [item for item in await self.list_tools() if item["tool_id"] == tool_id]
            if len(entries) != 1:
                raise ExpectedToolInputError("Registered mission tool ID was not found in this run")
            metadata, body = await self.artifacts.read(
                entries[0]["definition_artifact_id"], limit=None
            )
            try:
                definition = json.loads(body)
                valid = (
                    metadata["kind"] == "mission_tool_definition"
                    and definition == metadata["tool_definition"]
                    and definition["tool_id"] == tool_id
                    and definition["run_id"] == self.run["run_id"]
                    and definition["created_by"] == "tools_rd_lead"
                )
                if not valid:
                    raise ValueError
                validate_arguments(definition["input_schema"], arguments)
                source_meta, source = await self.artifacts.read(
                    definition["source_artifact_id"], limit=None
                )
                if (
                    source_meta["kind"] != "mission_tool_source"
                    or source_meta["sha256"] != definition["source_sha256"]
                ):
                    raise ValueError
                receipts = [
                    await self.artifacts.read(item, limit=None)
                    for item in definition["test_artifact_ids"]
                ]
                if not any(
                    m.get("kind") == "command_result" and json.loads(content).get("exit_code") == 0
                    for m, content in receipts
                ):
                    raise ValueError
            except (KeyError, TypeError, ValueError) as exc:
                raise ExpectedToolInputError(
                    "Registered mission tool evidence failed validation"
                ) from exc
            result = await self._run(host, call_id, source, arguments)
            usage = await self.artifacts.save(
                f"{definition['name']}-tool-use.json",
                bounded_json(
                    {
                        "tool_id": tool_id,
                        "tool_name": definition["name"],
                        "registered_by": definition["created_by"],
                        "invoked_by": host.role,
                        "definition_artifact_id": metadata["artifact_id"],
                        "source_artifact_id": definition["source_artifact_id"],
                        "source_sha256": definition["source_sha256"],
                        "test_artifact_ids": definition["test_artifact_ids"],
                        "arguments": arguments,
                        "output": result["output"],
                        "execution_artifact_ids": result["receipt"]["artifact_ids"],
                    },
                    limit=100000,
                ),
                kind="mission_tool_use",
                kr_id=host.kr_id,
                department=host.department,
                epoch=host.epoch,
                version=host.version,
                scope=host.scope,
                write_id=host.operation_id(call_id, "mission_tool_use"),
            )
            return {
                "tool_id": tool_id,
                "output": result["output"],
                "artifact_ids": [usage["artifact_id"], *result["receipt"]["artifact_ids"]],
            }

        return await host.journal(
            call_id,
            "run_mission_tool",
            {"tool_id": tool_id, "arguments": arguments},
            execute,
        )
