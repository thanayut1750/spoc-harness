"""Durable activity can be restored without replaying old work into the live office."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.storage import MemoryStorage, PostgresStorage


async def exercise_history(storage, tmp_path):
    app = create_app(Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path), storage)
    events = []
    for index, (source, agent_id, run_id) in enumerate(
        [
            ("harness", "backend_coder", "run-one"),
            ("external", "backend_coder", "run-one"),
            ("harness", "market_researcher", "run-one"),
            ("harness", "backend_coder", "run-two"),
            ("harness", "backend_coder", "run-one"),
            ("external", "backend_coder", "run-two"),
            ("harness", "specialist:run-one:0123456789abcdef", "run-one"),
            ("harness", "backend_coder", "run-one"),
        ]
    ):
        events.append(
            await storage.emit(
                {
                    "event_id": f"event-{index}",
                    "source": source,
                    "agent_id": agent_id,
                    "run_id": run_id,
                    "activity": "executing",
                    "summary": f"Recorded action {index}",
                    "data": {"tool": "write_file"},
                }
            )
        )
    snapshot = await storage.office_snapshot()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        latest = (await client.get("/api/events/history", params={"limit": 3})).json()
        assert latest == {
            "events": list(reversed(events[5:])),
            "next_before": 6,
            "has_more": True,
            "cursor": 8,
            "generation": snapshot["generation"],
            "reset": False,
        }
        middle = (
            await client.get(
                "/api/events/history", params={"limit": 3, "before": latest["next_before"]}
            )
        ).json()
        oldest = (
            await client.get(
                "/api/events/history", params={"limit": 3, "before": middle["next_before"]}
            )
        ).json()
        assert [event["seq"] for event in middle["events"]] == [5, 4, 3]
        assert [event["seq"] for event in oldest["events"]] == [2, 1]
        assert oldest["next_before"] is None and not oldest["has_more"]
        assert latest["events"] + middle["events"] + oldest["events"] == list(reversed(events))
        filtered = (
            await client.get(
                "/api/events/history",
                params={
                    "run_id": "run-one",
                    "agent_id": "backend_coder",
                    "source": "harness",
                    "limit": 2,
                },
            )
        ).json()
        assert [event["seq"] for event in filtered["events"]] == [8, 5]
        earlier = (
            await client.get(
                "/api/events/history",
                params={
                    "run_id": "run-one",
                    "agent_id": "backend_coder",
                    "source": "harness",
                    "before": filtered["next_before"],
                    "limit": 2,
                },
            )
        ).json()
        assert earlier["events"] == [events[0]] and not earlier["has_more"]
        external = (
            await client.get(
                "/api/events/history", params={"source": "external", "agent_id": "backend_coder"}
            )
        ).json()
        assert external["events"] == [events[5], events[1]]
        dynamic = (
            await client.get(
                "/api/events/history", params={"agent_id": "specialist:run-one:0123456789abcdef"}
            )
        ).json()
        assert dynamic["events"] == [events[6]]
        missing = (await client.get("/api/events/history", params={"run_id": "missing"})).json()
        assert missing["events"] == [] and missing["next_before"] is None
        for params in ({"limit": 0}, {"limit": 501}, {"before": 0}, {"source": ""}):
            assert (await client.get("/api/events/history", params=params)).status_code == 422
        # History reads leave projection and forward SSE replay cursor untouched.
        assert await storage.office_snapshot() == snapshot
        added = await storage.emit(
            {"agent_id": "backend_coder", "activity": "completed", "run_id": "run-one"}
        )
        anchored = (
            await client.get(
                "/api/events/history",
                params={"before": snapshot["cursor"] + 1, "generation": snapshot["generation"]},
            )
        ).json()
        assert anchored["events"] == list(reversed(events))
        assert await storage.events_after(snapshot["cursor"]) == [added]
        # A reload/reset can reuse sequence numbers. The old epoch must never
        # blend its earlier pages with new events even if the cursor has caught up.
        await storage.reset_data()
        for index in range(10):
            await storage.emit(
                {"agent_id": "executive", "activity": "planning", "event_id": f"new-{index}"}
            )
        stale = (
            await client.get(
                "/api/events/history",
                params={"before": 9, "generation": snapshot["generation"]},
            )
        ).json()
        assert stale["reset"] and stale["events"] == []
        assert stale["cursor"] == 10 and stale["generation"] != snapshot["generation"]
        assert stale["next_before"] is None and not stale["has_more"]
        current = (await client.get("/api/events/history")).json()
        assert not current["reset"] and len(current["events"]) == 10
        assert current["events"][0]["event_id"] == "new-9"
        return current


async def exercise_history_text_boundaries(storage, tmp_path, monkeypatch):
    app = create_app(Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path), storage)
    text = {"source": "ทีมอิสระ", "agent_id": "วิศวกร😀", "run_id": "mission-ไทย😀"}
    event = await storage.emit({**text, "activity": "reading"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        valid = (await client.get("/api/events/history", params=text)).json()
        assert valid["events"] == [event]
        for field in ("run_id", "agent_id", "source", "generation"):
            with pytest.raises(ValueError, match="Text contains"):
                await storage.event_history(**{field: "invalid\x00value"})
        calls = []

        async def forbidden_storage_access(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("Malformed HTTP text reached storage")

        with monkeypatch.context() as context:
            for method in (
                "event_history",
                "events_after",
                "get_reset_generation",
                "get_run",
                "get_artifact",
                "create_run",
            ):
                context.setattr(storage, method, forbidden_storage_access)
            for endpoint, params in (
                ("/api/events/history", {"run_id": "bad\x00"}),
                ("/api/events/history", {"agent_id": "bad\x00"}),
                ("/api/events/history", {"source": "bad\x00"}),
                ("/api/events/history", {"generation": "bad\x00"}),
                ("/api/events", {"run_id": "bad\x00"}),
                ("/api/runs/bad%00id", {}),
                ("/api/artifacts/bad%00id", {}),
            ):
                response = await asyncio.wait_for(client.get(endpoint, params=params), timeout=1)
                assert response.status_code == 422
            response = await client.post(
                "/api/runs",
                json={"user_request": "Unchanged mission"},
                headers={"Idempotency-Key": "bad\x00"},
            )
            assert response.status_code == 422
        assert calls == []
    assert (await storage.office_snapshot())["cursor"] == 1


async def test_memory_history_identifier_validation_precedes_storage_access(tmp_path, monkeypatch):
    await exercise_history_text_boundaries(MemoryStorage(), tmp_path, monkeypatch)


async def test_memory_history_restores_pages_filters_and_reset_generation(tmp_path):
    await exercise_history(MemoryStorage(), tmp_path)


@pytest.mark.integration
async def test_postgres_history_survives_reopen_with_pages_filters_and_reset(
    tmp_path, postgres_url
):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        history = await exercise_history(storage, tmp_path)
    finally:
        await storage.close()
    restored = PostgresStorage(postgres_url)
    await restored.open()
    try:
        assert await restored.event_history() == history
    finally:
        await restored.close()


@pytest.mark.integration
async def test_postgres_history_identifier_validation_precedes_storage_access(
    tmp_path, postgres_url, monkeypatch
):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        await exercise_history_text_boundaries(storage, tmp_path, monkeypatch)
    finally:
        await storage.close()


@pytest.mark.integration
@pytest.mark.parametrize("read_method", ["office_snapshot", "event_history"])
async def test_postgres_event_reads_finish_consistently_while_reset_waits_for_their_lock(
    postgres_url, monkeypatch, read_method
):
    storage, resetter = PostgresStorage(postgres_url), PostgresStorage(postgres_url)
    await storage.open()
    await resetter.open()
    original_pool = storage.pool
    first_read = asyncio.Event()
    continue_read = asyncio.Event()
    tasks = []

    class PausedConnection:
        def __init__(self, connection):
            self.connection = connection

        def transaction(self):
            return self.connection.transaction()

        async def execute(self, query, *args, **kwargs):
            result = await self.connection.execute(query, *args, **kwargs)
            if str(query).startswith("SELECT") and not first_read.is_set():
                first_read.set()
                await continue_read.wait()
            return result

    class PausedPool:
        @asynccontextmanager
        async def connection(self):
            async with original_pool.connection() as connection:
                yield PausedConnection(connection)

    try:
        await storage.migrate()
        await storage.emit({"agent_id": "executive", "activity": "planning"})
        await storage.emit({"agent_id": "backend_coder", "activity": "writing"})
        original_generation = await storage.get_reset_generation()
        with monkeypatch.context() as context:
            context.setattr(storage, "pool", PausedPool())
            reading = asyncio.create_task(getattr(storage, read_method)())
            tasks.append(reading)
            await asyncio.wait_for(first_read.wait(), timeout=3)
            resetting = asyncio.create_task(resetter.reset_data())
            tasks.append(resetting)

            async def reset_is_waiting_for_lock():
                async with resetter.pool.connection() as connection:
                    while True:
                        row = await (
                            await connection.execute(
                                """SELECT 1 FROM pg_stat_activity
                                WHERE datname=current_database() AND wait_event_type='Lock'
                                AND query LIKE 'TRUNCATE %%'"""
                            )
                        ).fetchone()
                        if row:
                            return
                        await asyncio.sleep(0.01)

            await asyncio.wait_for(reset_is_waiting_for_lock(), timeout=3)
            continue_read.set()
            snapshot, _ = await asyncio.wait_for(asyncio.gather(reading, resetting), timeout=4)
        assert snapshot["cursor"] == 2 and snapshot["generation"] == original_generation
        assert len(snapshot["agents" if read_method == "office_snapshot" else "events"]) == 2
        empty = await storage.office_snapshot()
        assert empty["cursor"] == 0 and empty["agents"] == []
        assert empty["generation"] != original_generation
    finally:
        continue_read.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await storage.close()
        await resetter.close()
