"""Private async workspaces separate task identity from capability authority."""

import asyncio
import json

import pytest

from org_harness.config import Settings
from org_harness.mission_tools import MissionToolCatalog
from org_harness.models import EscalationSignal, RunCreate
from org_harness.storage import MemoryStorage
from org_harness.tools import Artifacts, ExpectedToolInputError, HostTools


async def hosts(tmp_path):
    project = tmp_path / "user-project"
    project.mkdir()
    (project / "tool.py").write_text("original user source")
    storage = MemoryStorage()
    run = await storage.create_run(
        RunCreate(user_request="Isolate delegated work", workspace_path=str(project)).model_dump(
            mode="json"
        )
    )
    artifacts = Artifacts(storage, tmp_path / "managed", run["run_id"])
    events = []

    async def emit(actor, activity, summary, **data):
        events.append({"agent_id": actor, "activity": activity, "summary": summary, **data})

    def create(**kwargs):
        return HostTools(
            storage,
            artifacts,
            run,
            **{
                "kr_id": "KR1",
                "department": "engineering",
                "epoch": 0,
                "version": 1,
                "role": "tools_rd_lead",
                "work_package_id": "delegation",
                "emit": emit,
                **kwargs,
            },
        )

    return storage, run, artifacts, project, events, create


async def test_actor_alias_preserves_capability_role_and_owns_all_public_effects(tmp_path):
    storage, run, artifacts, project, events, create = await hosts(tmp_path)
    actor = f"specialist:{run['run_id']}:rd-task-one"
    host = create(actor_id=actor)
    assert host.role == "tools_rd_lead" and host.actor_id == actor
    assert host.workspace == project  # R&D's explicit private run path is not relocated.
    assert json.loads(host.scope) == ["delegation", 0, actor]
    await host.write_file("write", "report.md", "Verified report")
    assert (await host.read_file("read", "report.md"))["content"] == "Verified report"
    await host.publish_file("publish", "report.md")

    async def research():
        return {"verified": True}

    await host.record_research("source", "web_reader", {"url": "fixture"}, research)
    result = await host.run_command("command", "printf verified")
    assert result["exit_code"] == 0
    assert events and {event["agent_id"] for event in events} == {actor}
    assert {event["activity"] for event in events} == {"writing", "reading", "executing"}
    saved = await storage.list_artifacts(run["run_id"])
    assert saved and all(json.loads(item["scope"])[2] == actor for item in saved)
    manifest = json.loads(
        (
            artifacts.root
            / "operations"
            / f"{host.operation_id('command', 'run_command')}.process.json"
        ).read_text()
    )
    assert manifest["actor_id"] == actor


async def test_async_siblings_keep_private_files_and_retry_stable_cwd_with_distinct_attempts(
    tmp_path,
):
    storage, run, artifacts, project, _, create = await hosts(tmp_path)
    alpha = create(actor_id="specialist:run:alpha", isolated_workspace=True)
    beta = create(actor_id="specialist:run:beta", isolated_workspace=True)
    assert alpha.workspace != beta.workspace
    managed = artifacts.root.parent.parent / "workspaces" / run["run_id"] / "KR1" / "1" / "0"
    assert alpha.workspace.parent == beta.workspace.parent == managed / "async"
    results = await asyncio.gather(
        alpha.write_file("same-call", "tool.py", "alpha source"),
        beta.write_file("same-call", "tool.py", "beta source"),
    )
    assert (alpha.workspace / "tool.py").read_text() == "alpha source"
    assert (beta.workspace / "tool.py").read_text() == "beta source"
    assert (project / "tool.py").read_text() == "original user source"
    assert results[0]["artifact_id"] != results[1]["artifact_id"]
    before = (await storage.get_run(run["run_id"]))["tool_calls"]
    replay = create(actor_id=alpha.actor_id, isolated_workspace=True)
    assert replay.workspace == alpha.workspace
    assert await replay.write_file("same-call", "tool.py", "alpha source") == results[0]
    assert (await storage.get_run(run["run_id"]))["tool_calls"] == before
    repair = create(actor_id=alpha.actor_id, isolated_workspace=True, attempt=1)
    assert repair.workspace == alpha.workspace
    assert repair.scope != alpha.scope
    assert repair.operation_id("same-call", "write_file") != alpha.operation_id(
        "same-call", "write_file"
    )
    changed = await repair.write_file("same-call", "tool.py", "repaired alpha")
    assert changed["artifact_id"] != results[0]["artifact_id"]
    assert (await artifacts.read(results[0]["artifact_id"]))[1] == "alpha source"
    assert (await artifacts.read(changed["artifact_id"]))[1] == "repaired alpha"
    assert (
        create(actor_id=alpha.actor_id, isolated_workspace=True, version=2).workspace
        != alpha.workspace
    )
    assert (
        create(actor_id=alpha.actor_id, isolated_workspace=True, epoch=1).workspace
        != alpha.workspace
    )
    assert (
        create(actor_id=alpha.actor_id, isolated_workspace=True, work_package_id="other").workspace
        != alpha.workspace
    )


async def test_isolated_file_tools_reject_absolute_parent_and_symlink_escapes(tmp_path):
    storage, run, _, project, _, create = await hosts(tmp_path)
    host = create(actor_id="specialist:run:private", isolated_workspace=True)
    (host.workspace / "linked").symlink_to(project, target_is_directory=True)
    for index, path in enumerate((str(project / "tool.py"), "../../outside.py", "linked/tool.py")):
        with pytest.raises(ExpectedToolInputError, match="private workspace"):
            host.path(path)
        for result in await asyncio.gather(
            host.read_file(f"read-{index}", path),
            host.write_file(f"write-{index}", path, "do not write"),
            host.publish_file(f"publish-{index}", path),
        ):
            assert result["error"] == "ExpectedToolInputError"
            assert "private workspace" in result["detail"]
    assert (project / "tool.py").read_text() == "original user source"
    assert not await storage.list_artifacts(run["run_id"])
    saved = await host.write_file("safe", "nested/report.md", "private output")
    assert "error" not in saved
    assert (await host.read_file("absolute-inside", str(host.workspace / "nested/report.md")))[
        "content"
    ] == "private output"


async def test_sync_paths_and_legacy_actor_scope_keep_existing_behavior(tmp_path):
    _, _, _, project, events, create = await hosts(tmp_path)
    host = create(role="backend_coder")
    assert host.workspace == project
    assert host.actor_id == host.role == "backend_coder"
    assert json.loads(host.scope) == ["delegation", 0, "backend_coder"]
    outside = tmp_path / "legacy-output.txt"
    assert "error" not in await host.write_file("absolute", str(outside), "legacy absolute output")
    assert (await host.read_file("parent", "../legacy-output.txt"))[
        "content"
    ] == "legacy absolute output"
    assert outside.read_text() == "legacy absolute output"
    assert all(event["agent_id"] == "backend_coder" for event in events)
    managed = HostTools(
        host.storage,
        host.artifacts,
        {**host.run, "workspace_path": None},
        kr_id="KR1",
        department="engineering",
        epoch=0,
        role="backend_coder",
        emit=host.emit,
    )
    assert (
        managed.workspace
        == host.artifacts.root.parent.parent / "workspaces" / host.run["run_id"] / "KR1" / "0"
    )


async def test_display_actor_alias_cannot_grant_tools_rd_registration_authority(tmp_path):
    storage, run, artifacts, _, _, create = await hosts(tmp_path)
    host = create(role="backend_coder", actor_id="tools_rd_lead")
    catalog = MissionToolCatalog(
        Settings(_env_file=None, data_dir=tmp_path / "managed"), storage, run, artifacts
    )
    with pytest.raises(EscalationSignal) as raised:
        await catalog.register(
            host,
            "forged-register",
            name="fake_privilege",
            description="A displayed identity is not authority",
            source_path="tool.py",
            input_schema={"type": "object"},
            example_arguments={},
        )
    assert raised.value.kind == "policy_violation"
    assert not await storage.list_artifacts(run["run_id"])
