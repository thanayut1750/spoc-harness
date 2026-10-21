"""Public dynamic identities survive durable status events without copying work evidence."""

import pytest

from org_harness.storage import MemoryStorage, PostgresStorage


async def _exercise_identity_projection(
    storage: MemoryStorage | PostgresStorage, agent_type: str = "engineering_specialist"
) -> dict:
    specialist = "specialist:run-one:1234567890abcdef"
    identity = {
        "agent_type": agent_type,
        "display_name": "Browser verification specialist",
        "parent_agent_id": "engineering_head",
        "department": "engineering",
        "model_parent": "backend_coder",
        "base_role": "backend_coder",
    }
    if agent_type == "research_specialist":
        identity.update(
            parent_agent_id="research_head",
            department="research",
            model_parent="market_researcher",
            base_role="market_researcher",
        )
    elif agent_type == "tools_rd_task":
        identity.update(
            parent_agent_id="planner",
            model_parent="tools_rd_lead",
            base_role="tools_rd_lead",
            task_id="durable-research-job",
            parent_task_id="planner-invocation",
            execution_mode="async",
        )
    initial = {
        "source": "harness",
        "agent_id": specialist,
        "run_id": "run-one",
        "event_id": "activate-specialist",
        "activity": "executing",
        "data": {**identity, "artifact_ids": ["old-evidence"], "score": 0.1},
    }
    activated = await storage.emit(initial)
    assert activated["display_name"] == identity["display_name"]
    bare = {
        "source": "harness",
        "agent_id": specialist,
        "run_id": "run-one",
        "event_id": "specialist-tool-completed",
        "activity": "completed",
        "data": {"tool": "publish_file"},
    }
    latest = await storage.emit(bare)
    assert latest["data"] == {**identity, "tool": "publish_file"}
    assert latest["display_name"] == identity["display_name"]
    # Replays preserve the original stored event, even after newer identity changes.
    await storage.emit(
        {**bare, "event_id": "renamed-specialist", "data": {"display_name": "Updated name"}}
    )
    assert await storage.emit(bare) == latest
    assert initial["data"].get("tool") is None
    historical = await storage.events_after(activated["seq"])
    assert historical[0] == latest
    assert historical[1]["data"] == {**identity, "display_name": "Updated name"}
    assert historical[1]["display_name"] == "Updated name"

    # External agents may reuse IDs and public metadata but cannot inherit internal identity.
    external = {**initial, "source": "external", "event_id": "external-activation"}
    external_first = await storage.emit(external)
    assert "display_name" not in external_first
    external_latest = await storage.emit(
        {**bare, "source": "external", "event_id": "external-completion"}
    )
    assert external_latest["data"] == {"tool": "publish_file"}
    assert "display_name" not in external_latest

    rd = {
        "source": "harness",
        "agent_id": "tools_rd_lead",
        "run_id": "run-one",
        "event_id": "rd-activation",
        "activity": "planning",
        "data": {
            "agent_type": "tools_rd_lead",
            "display_name": "Tools R&D Lead",
            "parent_agent_id": "planner",
            "department": "engineering",
            "model_parent": "tools_rd_lead",
        },
    }
    await storage.emit(rd)
    same_run = await storage.emit(
        {**rd, "event_id": "rd-completion", "activity": "completed", "data": {}}
    )
    assert same_run["data"] == rd["data"]
    assert same_run["display_name"] == "Tools R&D Lead"
    other_run = await storage.emit(
        {**rd, "run_id": "run-two", "event_id": "rd-other-run", "data": {}}
    )
    assert other_run["data"] == {}
    assert "display_name" not in other_run

    # Neither missing run scope nor incorrectly tagged fixed actors is inheritable.
    for actor, run_id in (("backend_coder", "run-one"), ("specialist:no-run", None)):
        first = {**initial, "agent_id": actor, "run_id": run_id, "event_id": f"{actor}-first"}
        await storage.emit(first)
        result = await storage.emit(
            {**first, "event_id": f"{actor}-last", "data": {"tool": "read_file"}}
        )
        assert result["data"] == {"tool": "read_file"}
        assert "display_name" not in result

    # An explicit type change must not resurrect the prior dynamic metadata.
    changed_type = await storage.emit(
        {**bare, "event_id": "specialist-type-change", "data": {"agent_type": "external"}}
    )
    assert changed_type["data"] == {"agent_type": "external"}
    assert "display_name" not in changed_type
    snapshot = await storage.office_snapshot()
    by_key = {(event["source"], event["agent_id"]): event for event in snapshot["agents"]}
    assert by_key[("external", specialist)] == external_latest
    assert by_key[("harness", specialist)] == changed_type
    assert by_key[("harness", "tools_rd_lead")] == other_run
    return snapshot


@pytest.mark.parametrize(
    "agent_type", ["engineering_specialist", "research_specialist", "tools_rd_task"]
)
async def test_memory_projection_retains_only_scoped_internal_identity(agent_type):
    await _exercise_identity_projection(MemoryStorage(), agent_type)


@pytest.mark.integration
@pytest.mark.parametrize(
    "agent_type", ["engineering_specialist", "research_specialist", "tools_rd_task"]
)
async def test_postgres_projection_and_history_retain_identity_after_reopen(
    postgres_url, agent_type
):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        snapshot = await _exercise_identity_projection(storage, agent_type)
        history = await storage.events_after()
    finally:
        await storage.close()
    reopened = PostgresStorage(postgres_url)
    await reopened.open()
    try:
        assert await reopened.office_snapshot() == snapshot
        assert await reopened.events_after() == history
    finally:
        await reopened.close()
