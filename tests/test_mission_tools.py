"""Generated tools stay mission-scoped, tested, immutable and journaled."""

import asyncio
import json
from pathlib import Path

import pytest

from org_harness.config import Settings
from org_harness.mission_tools import MissionToolCatalog
from org_harness.models import EscalationSignal, RunCreate
from org_harness.storage import MemoryStorage, PostgresStorage
from org_harness.tools import Artifacts, HostTools

SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}
SOURCE = (
    "import json,sys\ndata=json.load(sys.stdin)\nprint(json.dumps({'doubled':data['value']*2}))\n"
)


async def environment(tmp_path, storage=None):
    storage = storage or MemoryStorage()
    settings = Settings(_env_file=None, data_dir=tmp_path)
    run = await storage.create_run(
        RunCreate(user_request="Build a useful tool").model_dump(mode="json")
    )
    artifacts = Artifacts(storage, tmp_path, run["run_id"])

    async def emit(*args, **kwargs):
        pass

    def host(role, kr="engineering-1"):
        return HostTools(
            storage,
            artifacts,
            run,
            kr_id=kr,
            department="engineering",
            epoch=0,
            role=role,
            work_package_id=role,
            emit=emit,
        )

    rd = host("tools_rd_lead", "tools-rd")
    (rd.workspace / "double.py").write_text(SOURCE)
    return storage, run, artifacts, MissionToolCatalog(settings, storage, run, artifacts), rd, host


async def register(catalog, rd, call="register", **changes):
    arguments = dict(
        name="double",
        description="Double an integer",
        source_path="double.py",
        input_schema=SCHEMA,
        example_arguments={"value": 3},
    )
    return await catalog.register(rd, call, **{**arguments, **changes})


async def test_tool_survives_catalog_rebuild_and_runs_in_another_kr(tmp_path):
    storage, run, artifacts, catalog, rd, host = await environment(tmp_path)
    tool = await register(catalog, rd)
    assert tool["smoke_test_passed"]
    assert len(await catalog.list_tools()) == 1
    # The immutable source survives edits to the original R&D file.
    (rd.workspace / "double.py").write_text("raise RuntimeError('changed original')")
    restored = MissionToolCatalog(None, storage, run, artifacts)
    worker = host("backend_coder")
    result = await restored.invoke(worker, "use", tool_id=tool["tool_id"], arguments={"value": 7})
    assert result["output"] == {"doubled": 14}
    assert result["artifact_ids"]
    receipts = [
        a for a in await storage.list_artifacts(run["run_id"]) if a["kind"] == "command_result"
    ]
    assert len(receipts) == 2 and {a["kr_id"] for a in receipts} == {"tools-rd", "engineering-1"}
    usage = [
        a for a in await storage.list_artifacts(run["run_id"]) if a["kind"] == "mission_tool_use"
    ]
    proof = json.loads(Path(usage[0]["path"]).read_text())
    assert proof["registered_by"] == "tools_rd_lead"
    assert proof["invoked_by"] == "backend_coder"
    assert proof["definition_artifact_id"] == tool["definition_artifact_id"]
    assert proof["output"] == {"doubled": 14}
    current = await worker.recorded_artifacts(current=True)
    assert usage[0]["artifact_id"] in {a["artifact_id"] for a in current}
    assert not any(a["kind"] == "source" for a in current)  # Runtime copies are supporting data.


async def test_catalog_and_usage_preserve_revised_kr_version_and_epoch(tmp_path):
    storage, run, _, catalog, rd, host = await environment(tmp_path)
    rd.version = 2
    rd.epoch = 3
    tool = await register(catalog, rd)
    evidence = await rd.recorded_artifacts(current=True)
    assert tool["source_artifact_id"] in {a["artifact_id"] for a in evidence}
    assert tool["definition_artifact_id"] in {a["artifact_id"] for a in evidence}
    assert all(a["version"] == 2 and a["epoch"] == 3 for a in evidence)
    worker = host("backend_coder")
    worker.version = 2
    worker.epoch = 3
    result = await catalog.invoke(worker, "use", tool_id=tool["tool_id"], arguments={"value": 9})
    assert result["output"] == {"doubled": 18}
    current = await worker.recorded_artifacts(current=True)
    assert all(a["version"] == 2 and a["epoch"] == 3 for a in current)
    assert any(a["kind"] == "mission_tool_use" for a in current)


async def test_tool_registration_and_concurrent_invocation_replay_exactly_once(tmp_path):
    storage, run, _, catalog, rd, host = await environment(tmp_path)
    marker = rd.workspace / "effects.txt"
    script = SOURCE.replace(
        "print(json.dumps", f"open({str(marker)!r},'a').write('executed\\n')\nprint(json.dumps"
    )
    (rd.workspace / "double.py").write_text(script)
    tool = await register(catalog, rd)
    assert await register(catalog, rd) == tool
    worker = host("backend_coder")
    results = await asyncio.gather(
        *[
            catalog.invoke(worker, "use", tool_id=tool["tool_id"], arguments={"value": 4})
            for _ in range(3)
        ]
    )
    assert results[0] == results[1] == results[2]
    assert marker.read_text().splitlines() == ["executed", "executed"]
    assert not await storage.uncertain_operations(run["run_id"])


async def test_tool_registration_requires_private_rd_actor(tmp_path):
    storage, run, _, catalog, _, host = await environment(tmp_path)
    for caller in ("backend_coder", "planner", "engineering_head", "research_head", "executive"):
        with pytest.raises(EscalationSignal) as error:
            await register(catalog, host(caller))
        assert error.value.kind == "policy_violation"
    assert not storage.operations
    assert (await storage.get_run(run["run_id"]))["tool_calls"] == 0


async def test_tool_ids_and_hosts_cannot_cross_mission_boundaries(tmp_path):
    _, _, _, catalog, rd, host = await environment(tmp_path / "first")
    tool = await register(catalog, rd)
    _, _, _, other, _, other_host = await environment(tmp_path / "second")
    with pytest.raises(EscalationSignal) as error:
        await catalog.invoke(
            other_host("backend_coder"), "foreign", tool_id=tool["tool_id"], arguments={"value": 2}
        )
    assert error.value.kind == "policy_violation"
    result = await other.invoke(
        other_host("backend_coder"), "foreign", tool_id=tool["tool_id"], arguments={"value": 2}
    )
    assert result["error"] == "ExpectedToolInputError"
    assert not (host("backend_coder").workspace / ".mission-tools").exists()


@pytest.mark.parametrize(
    "arguments",
    [{"value": "wrong"}, {"value": True}, {"value": 3, "extra": 1}, {"value": float("nan")}],
)
async def test_invalid_arguments_do_not_execute_tool(tmp_path, arguments):
    storage, run, _, catalog, rd, host = await environment(tmp_path)
    tool = await register(catalog, rd)
    before = len(
        [a for a in await storage.list_artifacts(run["run_id"]) if a["kind"] == "command_result"]
    )
    result = await catalog.invoke(
        host("backend_coder"), "bad", tool_id=tool["tool_id"], arguments=arguments
    )
    assert result["error"] == "ExpectedToolInputError"
    after = len(
        [a for a in await storage.list_artifacts(run["run_id"]) if a["kind"] == "command_result"]
    )
    assert before == after == 1


@pytest.mark.parametrize(
    "schema", [{"type": "wrong"}, {"type": "object", "$ref": "https://invalid.test/schema"}]
)
async def test_invalid_or_network_referencing_schema_is_not_registered(tmp_path, schema):
    _, _, _, catalog, rd, _ = await environment(tmp_path)
    result = await register(catalog, rd, input_schema=schema)
    assert result["error"] == "ExpectedToolInputError"
    assert not await catalog.list_tools()


@pytest.mark.parametrize(
    "script", ["not valid python (", "raise RuntimeError('bad tool')", "print('not json')"]
)
async def test_broken_or_non_json_tools_never_become_available(tmp_path, script):
    _, _, _, catalog, rd, _ = await environment(tmp_path)
    (rd.workspace / "double.py").write_text(script)
    result = await register(catalog, rd)
    assert result["error"] == "ExpectedToolInputError"
    assert not await catalog.list_tools()


async def test_valid_json_prefix_cannot_hide_invalid_output_beyond_log_preview(tmp_path):
    _, _, _, catalog, rd, _ = await environment(tmp_path)
    (rd.workspace / "double.py").write_text(
        "import sys\nsys.stdout.write('{\"ok\": true}' + ' ' * 32768 + 'not-json')\n"
    )
    result = await register(catalog, rd)
    assert result["error"] == "ExpectedToolInputError"
    assert "output limit" in result["detail"]
    assert not await catalog.list_tools()


@pytest.mark.parametrize("tamper", ["source", "definition", "receipt"])
async def test_tampered_source_definition_or_test_receipts_block_execution(tmp_path, tamper):
    storage, _, _, catalog, rd, host = await environment(tmp_path)
    tool = await register(catalog, rd)
    key = {
        "source": tool["source_artifact_id"],
        "definition": tool["definition_artifact_id"],
        "receipt": tool["test_artifact_ids"][-1],
    }[tamper]
    artifact = await storage.get_artifact(key)
    Path(artifact["path"]).write_text("Changed evidence")
    worker = host("backend_coder")
    result = await catalog.invoke(worker, "use", tool_id=tool["tool_id"], arguments={"value": 3})
    assert result["error"] == "ExpectedToolInputError"
    assert not (worker.workspace / ".mission-tools").exists()


async def test_tool_versions_have_unique_ids_and_shell_values_stay_json_data(tmp_path):
    _, _, _, catalog, rd, host = await environment(tmp_path)
    (rd.workspace / "double.py").write_text(
        "import json,sys\nprint(json.dumps(json.load(sys.stdin)))\n"
    )
    schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    first = await register(catalog, rd, input_schema=schema, example_arguments={"text": "a"})
    second = await register(
        catalog, rd, call="register-again", input_schema=schema, example_arguments={"text": "a"}
    )
    assert first["tool_id"] != second["tool_id"]
    text = "'; touch must-not-exist; $(touch also-must-not-exist)\n"
    worker = host("backend_coder")
    result = await catalog.invoke(
        worker, "use", tool_id=second["tool_id"], arguments={"text": text}
    )
    assert result["output"] == {"text": text}
    assert not (worker.workspace / "must-not-exist").exists()
    assert not (worker.workspace / "also-must-not-exist").exists()


@pytest.mark.integration
async def test_postgres_catalog_persists_tested_tools_and_command_receipts(tmp_path, postgres_url):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        _, run, artifacts, catalog, rd, host = await environment(tmp_path, storage)
        tool = await register(catalog, rd)
        rebuilt = MissionToolCatalog(None, storage, run, artifacts)
        result = await rebuilt.invoke(
            host("backend_coder"), "persisted", tool_id=tool["tool_id"], arguments={"value": 8}
        )
        assert result["output"] == {"doubled": 16}
        assert (
            await rebuilt.invoke(
                host("backend_coder"), "persisted", tool_id=tool["tool_id"], arguments={"value": 8}
            )
            == result
        )
    finally:
        await storage.close()
