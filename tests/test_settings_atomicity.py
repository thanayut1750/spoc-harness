"""Independent API instances cannot lose omitted caps or sibling overrides."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.storage import MemoryStorage, PostgresStorage


class ObservedSettings:
    def __init__(self, storage, key):
        self.storage = storage
        self.key = key
        self.started = asyncio.Event()

    def __getattr__(self, name):
        return getattr(self.storage, name)

    async def get_setting(self, key):
        if key == self.key:
            self.started.set()
        return await self.storage.get_setting(key)

    async def update_setting(self, key, transform):
        if key == self.key:
            self.started.set()
        return await self.storage.update_setting(key, transform)


@asynccontextmanager
async def paused_setting_writes(storage, key):
    if isinstance(storage, MemoryStorage):
        async with storage.lock:
            yield
    else:
        async with storage.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,2))", (key,))
            yield


async def wait_for_blocked_postgres_writes(storage, count):
    async def wait():
        async with storage.pool.connection() as conn:
            while True:
                row = await (
                    await conn.execute(
                        "SELECT count(*) AS count FROM pg_stat_activity "
                        "WHERE datname=current_database() AND wait_event_type='Lock' "
                        "AND (query LIKE '%%harness_settings%%' OR query LIKE '%%pg_advisory_xact_lock%%')"
                    )
                ).fetchone()
                if row["count"] >= count:
                    return
                await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout=3)


async def interleave_requests(storage, peer, settings, key, first_request, second_request):
    first, second = ObservedSettings(storage, key), ObservedSettings(peer, key)
    tasks = []
    try:
        async with (
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_app(settings, first)),
                base_url="http://test",
            ) as client_a,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_app(settings, second)),
                base_url="http://test",
            ) as client_b,
        ):
            async with paused_setting_writes(storage, key):
                tasks.append(
                    asyncio.create_task(client_a.request(*first_request[:2], json=first_request[2]))
                )
                await asyncio.wait_for(first.started.wait(), timeout=3)
                if isinstance(storage, PostgresStorage):
                    await wait_for_blocked_postgres_writes(storage, 1)
                tasks.append(
                    asyncio.create_task(
                        client_b.request(*second_request[:2], json=second_request[2])
                    )
                )
                await asyncio.wait_for(second.started.wait(), timeout=3)
                if isinstance(storage, PostgresStorage):
                    await wait_for_blocked_postgres_writes(storage, 2)
            responses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
            assert all(response.status_code == 200 for response in responses)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def exercise_settings_interleaving(storage, peer, tmp_path):
    settings = Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path)
    await storage.save_setting(
        "model_call_budget",
        {"max_model_calls": 100, "worker_model_calls": 12, "max_tool_calls": 200},
    )
    await interleave_requests(
        storage,
        peer,
        settings,
        "model_call_budget",
        (
            "PUT",
            "/api/settings/budgets",
            {"max_model_calls": 900, "worker_model_calls": 13, "max_tool_calls": None},
        ),
        ("PUT", "/api/settings/budgets", {"max_model_calls": 101, "worker_model_calls": 17}),
    )
    assert await storage.get_setting("model_call_budget") == {
        "max_model_calls": 101,
        "worker_model_calls": 17,
        "max_tool_calls": None,
    }
    # A deletion of one override must not discard another concurrently added override.
    model = settings.default_model_selection().model_dump(mode="json")
    await storage.save_setting("agent_model_configs", {"system_architect": model})
    await interleave_requests(
        storage,
        peer,
        settings,
        "agent_model_configs",
        ("PUT", "/api/settings/agents/backend_coder", model),
        ("DELETE", "/api/settings/agents/system_architect", None),
    )
    assert await storage.get_setting("agent_model_configs") == {"backend_coder": model}
    # The same serialization must work before there is any row to lock.
    await storage.delete_setting("agent_model_configs")
    await interleave_requests(
        storage,
        peer,
        settings,
        "agent_model_configs",
        ("PUT", "/api/settings/agents/backend_coder", model),
        ("PUT", "/api/settings/agents/planner", model),
    )
    assert await storage.get_setting("agent_model_configs") == {
        "backend_coder": model,
        "planner": model,
    }
    before = await storage.get_setting("agent_model_configs")

    def failed_transform(current):
        current.clear()
        raise RuntimeError("Unexpected transform failure")

    with pytest.raises(RuntimeError, match="Unexpected transform failure"):
        await storage.update_setting("agent_model_configs", failed_transform)
    assert await storage.get_setting("agent_model_configs") == before


async def test_memory_workspace_partial_updates_are_atomic_across_api_instances(tmp_path):
    storage = MemoryStorage()
    await exercise_settings_interleaving(storage, storage, tmp_path)


@pytest.mark.integration
async def test_postgres_workspace_partial_updates_are_atomic_across_independent_pools(
    postgres_url, tmp_path
):
    storage, peer = PostgresStorage(postgres_url), PostgresStorage(postgres_url)
    await storage.open()
    await peer.open()
    try:
        await storage.migrate()
        await exercise_settings_interleaving(storage, peer, tmp_path)
    finally:
        await storage.close()
        await peer.close()
