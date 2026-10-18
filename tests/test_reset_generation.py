"""Reset epochs survive reconnects, sequence reuse, and API process replacement."""

import asyncio
from urllib.parse import urlencode

import pytest

from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.storage import MemoryStorage, PostgresStorage
from org_harness.worker import migrate


async def stream_until_reset(app, query, *, on_activity=None):
    sent = []
    finished = asyncio.Event()

    async def receive():
        await finished.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)
        body = message.get("body", b"")
        if b"event: activity" in body and on_activity is not None:
            await on_activity()
        if b"event: reset" in body:
            finished.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/events",
        "raw_path": b"/api/events",
        "query_string": urlencode(query).encode(),
        "headers": [(b"host", b"test")],
        "client": ("127.0.0.1", 1000),
        "server": ("test", 80),
        "root_path": "",
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=3)
    return b"".join(item.get("body", b"") for item in sent).decode()


async def test_memory_reset_changes_epoch_and_returns_consistent_snapshot():
    storage = MemoryStorage()
    original = await storage.get_reset_generation()
    await storage.emit({"agent_id": "backend_coder", "activity": "writing", "event_id": "old"})
    assert (await storage.office_snapshot())["generation"] == original
    await storage.reset_data()
    current = await storage.get_reset_generation()
    assert current != original
    assert await storage.office_snapshot() == {"cursor": 0, "agents": [], "generation": current}
    await storage.emit({"agent_id": "backend_coder", "activity": "writing", "event_id": "new"})
    assert (await storage.office_snapshot())["generation"] == current


@pytest.mark.parametrize("old_cursor", [1, 3])
async def test_reconnect_old_epoch_resets_even_when_new_sequences_reach_or_pass_cursor(
    tmp_path, old_cursor
):
    storage = MemoryStorage()
    original = await storage.get_reset_generation()
    await storage.reset_data()
    for index in range(3):
        await storage.emit(
            {"agent_id": "backend_coder", "activity": "writing", "event_id": str(index)}
        )
    app = create_app(Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path), storage)
    assert (await storage.office_snapshot())["cursor"] >= old_cursor
    body = await stream_until_reset(app, {"after": old_cursor, "generation": original})
    assert "event: reset" in body
    assert "event: activity" not in body


async def test_active_stream_notices_direct_storage_reset_without_process_local_signal(tmp_path):
    storage = MemoryStorage()
    original = await storage.get_reset_generation()
    await storage.emit({"agent_id": "backend_coder", "activity": "writing", "event_id": "old"})
    app = create_app(Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path), storage)

    async def direct_reset():
        await storage.reset_data()

    body = await stream_until_reset(
        app, {"after": 0, "generation": original}, on_activity=direct_reset
    )
    assert app.state.reset_generation == 0
    assert "event: activity" in body
    assert "event: reset" in body
    assert await storage.get_reset_generation() != original


@pytest.mark.integration
async def test_postgres_reset_epoch_survives_new_storage_and_api_instances(postgres_url, tmp_path):
    settings = Settings(_env_file=None, database_url=postgres_url, data_dir=tmp_path)
    await migrate(settings)
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        original = await storage.get_reset_generation()
        await storage.save_setting("model_config", {"model": "old-model"})
        await storage.reset_data()
        current = await storage.get_reset_generation()
        assert current != original
        assert await storage.get_setting("model_config") is None
    finally:
        await storage.close()
    restored = PostgresStorage(postgres_url)
    await restored.open()
    try:
        assert await restored.get_reset_generation() == current
        assert (await restored.office_snapshot())["generation"] == current
        for index in range(3):
            await restored.emit(
                {"agent_id": "backend_coder", "activity": "writing", "event_id": str(index)}
            )
        app = create_app(settings, restored)
        body = await stream_until_reset(app, {"after": 1, "generation": original})
        assert "event: reset" in body
        assert "event: activity" not in body
    finally:
        await restored.close()
