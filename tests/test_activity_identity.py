"""Source and raw actor IDs stay distinct in history, snapshots and upgrades."""

import copy

import httpx
import pytest

from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.storage import MemoryStorage, PostgresStorage


async def exercise_colliding_identities(storage, tmp_path):
    app = create_app(Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path), storage)
    internal = await storage.emit(
        {
            "source": "harness",
            "event_id": "internal",
            "agent_id": "specialist:mission:0123456789abcdef",
            "run_id": "mission",
            "activity": "writing",
            "summary": "Internal shader work",
            "data": {"agent_type": "engineering_specialist", "display_name": "Shader specialist"},
        }
    )
    identities = [
        ("specialist", "mission:0123456789abcdef"),
        ("a", "b:c"),
        ("a:b", "c"),
        ("a", '["a:b","c"]'),
        ("ทีม😀", 'quoted:"\\:วิศวกร'),
    ]
    events = [internal]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for index, (source, actor) in enumerate(identities):
            payload = {
                "source": source,
                "event_id": f"actor-{index}",
                "agent_id": actor,
                "activity": "reading",
                "summary": f"Integration {index}",
                "data": {"original": [source, actor], "proof": {"text": "unchanged"}},
            }
            response = await client.post("/api/integrations/events", json=payload)
            assert response.status_code == 202
            event = response.json()
            events.append(event)
            assert event["source"] == source and event["agent_id"] == actor
            assert event["data"] == payload["data"]
            assert (await client.post("/api/integrations/events", json=payload)).json() == event
            history = (
                await client.get(
                    "/api/events/history", params={"source": source, "agent_id": actor}
                )
            ).json()
            assert history["events"] == [event]
        snapshot = (await client.get("/api/office")).json()
    assert snapshot["cursor"] == len(events)
    assert len(snapshot["agents"]) == len(events)
    assert {(event["source"], event["agent_id"]): event for event in snapshot["agents"]} == {
        (event["source"], event["agent_id"]): event for event in events
    }
    assert await storage.events_after() == events
    return snapshot


async def test_memory_actor_projection_and_raw_history_isolate_ambiguous_ids(tmp_path):
    await exercise_colliding_identities(MemoryStorage(), tmp_path)


@pytest.mark.integration
async def test_postgres_actor_projection_isolation_survives_reopen(postgres_url, tmp_path):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        snapshot = await exercise_colliding_identities(storage, tmp_path)
    finally:
        await storage.close()
    reopened = PostgresStorage(postgres_url)
    await reopened.open()
    try:
        assert await reopened.office_snapshot() == snapshot
    finally:
        await reopened.close()


async def exercise_rolling_projection(storage, insert_legacy):
    internal = {
        "source": "harness",
        "event_id": "activation",
        "agent_id": "specialist:mission:0123456789abcdef",
        "run_id": "mission",
        "activity": "writing",
        "summary": "Old action",
        "data": {"agent_type": "engineering_specialist", "display_name": "Original name"},
    }
    first = await storage.emit(internal)
    # Simulate an older service writing its delimiter key during deployment.
    legacy = {
        **first,
        "seq": first["seq"] + 1,
        "event_id": "legacy-newer",
        "activity": "reading",
        "summary": "Newer legacy action",
        "display_name": "Current name",
        "data": {**first["data"], "display_name": "Current name", "stdout": "Old evidence"},
    }
    await insert_legacy(legacy)
    snapshot = await storage.office_snapshot()
    assert snapshot["agents"] == [legacy]
    updated = await storage.emit(
        {
            "source": "harness",
            "event_id": "new-completion",
            "agent_id": first["agent_id"],
            "run_id": "mission",
            "activity": "completed",
            "summary": "Completed current action",
        }
    )
    assert updated["display_name"] == "Current name"
    assert updated["data"] == {
        "agent_type": "engineering_specialist",
        "display_name": "Current name",
    }
    assert (await storage.office_snapshot())["agents"] == [updated]


async def test_memory_snapshot_deduplicates_legacy_rows_and_inherits_only_exact_identity():
    storage = MemoryStorage()

    async def insert_legacy(event):
        storage.projection[f"{event['source']}:{event['agent_id']}"] = copy.deepcopy(event)
        storage.events.append(copy.deepcopy(event))

    await exercise_rolling_projection(storage, insert_legacy)
    # This legacy key looks like a canonical tuple but belongs to another identity.
    foreign = {
        "source": "foreign",
        "agent_id": "other",
        "run_id": "mission",
        "seq": 100,
        "data": {"agent_type": "engineering_specialist", "display_name": "Forged"},
    }
    storage.projection['["harness","specialist:mission:ffffffffffffffff"]'] = foreign
    result = await storage.emit(
        {
            "agent_id": "specialist:mission:ffffffffffffffff",
            "run_id": "mission",
            "activity": "reading",
        }
    )
    assert result["data"] == {}
    assert "display_name" not in result


@pytest.mark.integration
async def test_postgres_snapshot_deduplicates_legacy_rows_and_uses_newest_identity(postgres_url):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()

        async def insert_legacy(event):
            async with storage.pool.connection() as conn, conn.transaction():
                await conn.execute(
                    "INSERT INTO harness_events(source,event_id,run_id,data) VALUES(%s,%s,%s,%s)",
                    (event["source"], event["event_id"], event["run_id"], storage._json(event)),
                )
                await conn.execute(
                    "INSERT INTO harness_projection(agent_key,data) VALUES(%s,%s)",
                    (f"{event['source']}:{event['agent_id']}", storage._json(event)),
                )

        await exercise_rolling_projection(storage, insert_legacy)
    finally:
        await storage.close()


@pytest.mark.integration
async def test_projection_migration_recovers_overwritten_actors_without_rewriting_history(
    postgres_url,
):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        run = await storage.create_run({"user_request": "Preserve this mission"})
        await storage.save_setting("reset_generation", {"value": "retained-generation"})
        events = []
        for index, (source, actor) in enumerate([("a", "b:c"), ("a:b", "c"), ("a", "b:c")]):
            events.append(
                await storage.emit(
                    {
                        "source": source,
                        "event_id": f"event-{index}",
                        "agent_id": actor,
                        "run_id": run["run_id"],
                        "activity": "reading",
                        "summary": f"Action {index}",
                        "data": {"text": 'Exact Unicode evidence 😀 "quoted" \\ slash\nnewline'},
                    }
                )
            )
        async with storage.pool.connection() as conn, conn.transaction():
            await conn.execute("DELETE FROM harness_projection")
            # The old delimiter key retained only the final actor of this collision.
            await conn.execute(
                "INSERT INTO harness_projection(agent_key,data) VALUES(%s,%s)",
                ("a:b:c", storage._json(events[-1])),
            )
            await conn.execute("DELETE FROM harness_migrations WHERE version=3")
        assert len((await storage.office_snapshot())["agents"]) == 1
        await storage.migrate()
        snapshot = await storage.office_snapshot()
        assert snapshot == {
            "agents": [events[-1], events[1]],
            "cursor": len(events),
            "generation": "retained-generation",
        }
        assert await storage.events_after() == events
        assert await storage.get_run(run["run_id"]) == run
        assert (
            await storage.emit({key: value for key, value in events[0].items() if key != "seq"})
            == events[0]
        )
        await storage.migrate()
        assert await storage.office_snapshot() == snapshot
    finally:
        await storage.close()
