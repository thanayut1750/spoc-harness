"""Model snapshots and destructive reset are exercised only on isolated state."""

import asyncio
import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore
from pydantic import SecretStr
from typing_extensions import TypedDict

from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.providers import create_model
from org_harness.reset import regenesis
from org_harness.storage import MemoryStorage, PostgresStorage
from org_harness.worker import migrate


@pytest.fixture
async def api(tmp_path):
    settings = Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path)
    storage = MemoryStorage()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, storage)), base_url="http://test"
    ) as client:
        yield client, storage, settings


async def test_model_settings_saved_and_snapshotted_without_secrets(api):
    client, storage, settings = api
    settings.openai_api_key = SecretStr("super-secret")
    initial = (await client.get("/api/settings")).json()
    assert initial["model_config"]["model"] == settings.main_model
    selection = {"provider": "configured", "model": "glm-test", "reasoning_effort": "low"}
    assert (await client.put("/api/settings/model", json=selection)).status_code == 200
    response = await client.post(
        "/api/runs",
        json={"user_request": "Build a website"},
        headers={"Idempotency-Key": "model-snapshot"},
    )
    assert response.status_code == 202
    run = await storage.get_run(response.json()["run_id"])
    assert run["model_config"] == selection
    await client.put("/api/settings/model", json={**selection, "model": "new-default"})
    assert (await storage.get_run(run["run_id"]))["model_config"] == selection
    replay = await client.post(
        "/api/runs",
        json={"user_request": "Build a website"},
        headers={"Idempotency-Key": "model-snapshot"},
    )
    assert replay.json() == response.json()
    overridden = await client.post(
        "/api/runs",
        json={"user_request": "One override", "model_config": {**selection, "model": "run-only"}},
    )
    assert (await storage.get_run(overridden.json()["run_id"]))["model_config"][
        "model"
    ] == "run-only"
    assert "super-secret" not in json.dumps((await client.get("/api/settings")).json())
    assert "super-secret" not in json.dumps(run)


async def test_unconfigured_provider_is_rejected_without_modifying_settings(tmp_path):
    settings = Settings(
        _env_file=None, openai_api_key="", standard_openai_api_key="", data_dir=tmp_path
    )
    storage = MemoryStorage()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, storage)), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/settings/model",
            json={"provider": "openai", "model": "gpt-5", "reasoning_effort": "high"},
        )
        assert response.status_code == 422
    assert await storage.get_setting("model_config") is None


async def test_agent_model_overrides_are_snapshotted_and_can_inherit_again(api):
    client, storage, _ = api
    selection = {"provider": "configured", "model": "review-model", "reasoning_effort": "high"}
    response = await client.put("/api/settings/agents/engineering_gatekeeper", json=selection)
    assert response.status_code == 200
    assert response.json()["agent_model_configs"] == {"engineering_gatekeeper": selection}
    response = await client.post("/api/runs", json={"user_request": "Build a website"})
    run_id = response.json()["run_id"]
    assert (await storage.get_run(run_id))["agent_model_configs"] == {
        "engineering_gatekeeper": selection
    }
    cleared = await client.delete("/api/settings/agents/engineering_gatekeeper")
    assert cleared.json()["agent_model_configs"] == {}
    assert (await storage.get_run(run_id))["agent_model_configs"] == {
        "engineering_gatekeeper": selection
    }
    assert (
        await client.put("/api/settings/agents/not-an-agent", json=selection)
    ).status_code == 422
    assert (
        await client.post(
            "/api/runs",
            json={"user_request": "invalid", "agent_model_configs": {"unknown": selection}},
        )
    ).status_code == 422


def test_provider_factory_keeps_zai_protocol_out_of_openai_requests():
    settings = Settings(_env_file=None, standard_openai_api_key="key", openai_api_key="zai-key")
    model = create_model(
        settings, {"provider": "openai", "model": "gpt-5", "reasoning_effort": "high"}
    )
    body = model._request(
        [
            HumanMessage(content="Build"),
            AIMessage(content="Working", additional_kwargs={"reasoning_content": "private"}),
        ]
    )
    assert body["reasoning_effort"] == "high"
    assert "extra_body" not in body
    assert "thinking" not in body
    assert "max_completion_tokens" in body
    assert "reasoning_content" not in body["messages"][1]
    assert model.base_url == "https://api.openai.com/v1"
    model.reasoning_effort = "none"
    assert model._request([HumanMessage(content="Build")])["reasoning_effort"] == "none"


async def test_regenesis_requires_confirmation_and_clears_managed_state(api, tmp_path):
    client, storage, settings = api
    run = await storage.create_run({"user_request": "Old data"})
    await storage.emit({"agent_id": "test", "activity": "writing", "summary": "old event"})
    await storage.save_setting(
        "model_config", {"provider": "configured", "model": "old", "reasoning_effort": "low"}
    )
    for name in ("workspaces", "artifacts"):
        directory = tmp_path / name / run["run_id"]
        directory.mkdir(parents=True)
        (directory / "old.txt").write_text("old data")
    # Infrastructure and external workspaces are outside the named deletion set.
    infrastructure = tmp_path / "pgdata"
    infrastructure.mkdir()
    (infrastructure / "sentinel").write_text("keep database infrastructure")
    external = tmp_path.parent / f"external-{run['run_id']}"
    external.mkdir()
    (external / "user.txt").write_text("keep")
    (tmp_path / "workspaces" / "external-link").symlink_to(external, target_is_directory=True)
    (tmp_path / "worker.log").write_text("old run log")
    bad = await client.post("/api/regenesis", json={"confirmation": "yes"})
    assert bad.status_code == 422
    assert len(await storage.list_runs()) == 1
    response = await client.post("/api/regenesis", json={"confirmation": "REGENESIS"})
    assert response.status_code == 200
    assert response.json()["removed_runs"] == 1
    assert (
        response.json()["settings"]["model_config"]
        == settings.default_model_selection().model_dump()
    )
    assert await storage.list_runs() == []
    snapshot = await storage.office_snapshot()
    assert snapshot["cursor"] == 0 and snapshot["agents"] == []
    assert snapshot["generation"] != "initial"
    assert (
        storage.jobs
        == storage.artifacts
        == storage.operations
        == storage.commands
        == storage.settings
        == {}
    )
    assert not (tmp_path / "artifacts").exists()
    assert not (tmp_path / "workspaces").exists()
    assert not (tmp_path / ".regenesis-trash").exists()
    assert (tmp_path / "worker.log").read_text() == ""
    assert (infrastructure / "sentinel").exists()
    assert (external / "user.txt").read_text() == "keep"


async def test_regenesis_cancels_active_execution_before_reset(api):
    client, storage, _ = api
    run = await storage.create_run({"user_request": "Working"})
    stopped = asyncio.Event()

    async def active_worker():
        async with storage.worker_lock():
            while not (await storage.get_run(run["run_id"])).get("cancel_requested"):
                await asyncio.sleep(0)
            stopped.set()

    worker = asyncio.create_task(active_worker())
    await asyncio.sleep(0)
    response = await client.post("/api/regenesis", json={"confirmation": "REGENESIS"})
    await worker
    assert response.status_code == 200
    assert stopped.is_set()
    assert await storage.list_runs() == []


async def test_memory_reset_removes_checkpoint_and_long_term_memory(api):
    _, storage, _ = api
    run = await storage.create_run({"user_request": "old"})
    saver, store = InMemorySaver(), InMemoryStore()

    class State(TypedDict):
        value: str

    graph = (
        StateGraph(State)
        .add_node("work", lambda _: {"value": "secret"})
        .add_edge(START, "work")
        .add_edge("work", END)
        .compile(checkpointer=saver)
    )
    config = {"configurable": {"thread_id": run["run_id"]}}
    await graph.ainvoke({"value": "old"}, config)
    await store.aput(("harness",), "remember", {"secret": "old"})
    storage.register_runtime_resources(saver, store)
    await storage.reset_data()
    assert await saver.aget_tuple(config) is None
    assert await store.asearch(("harness",)) == []


@pytest.mark.integration
async def test_postgres_regenesis_erases_checkpoints_store_and_application_state(
    postgres_url, tmp_path
):
    settings = Settings(_env_file=None, database_url=postgres_url, data_dir=tmp_path)
    await migrate(settings)
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.create_run({"user_request": "old data"})
        await storage.save_setting("model_config", {"model": "old"})
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres import AsyncPostgresStore

        class State(TypedDict):
            value: str

        async with AsyncPostgresSaver.from_conn_string(postgres_url) as saver:
            graph = (
                StateGraph(State)
                .add_node("work", lambda _: {"value": "old"})
                .add_edge(START, "work")
                .add_edge("work", END)
                .compile(checkpointer=saver)
            )
            await graph.ainvoke({"value": "old"}, {"configurable": {"thread_id": "old-thread"}})
        async with AsyncPostgresStore.from_conn_string(postgres_url) as store:
            await store.aput(("harness",), "old", {"data": "old"})
        async with storage.pool.connection() as conn:
            await conn.execute("CREATE TABLE unrelated_data (value text)")
            await conn.execute("INSERT INTO unrelated_data VALUES ('keep')")
        assert (await regenesis(settings, storage))["removed_runs"] == 1
        for name in (
            "harness_runs",
            "checkpoints",
            "checkpoint_writes",
            "checkpoint_blobs",
            "store",
        ):
            async with storage.pool.connection() as conn:
                from psycopg import sql

                row = await (
                    await conn.execute(
                        sql.SQL("SELECT count(*) AS count FROM {}").format(sql.Identifier(name))
                    )
                ).fetchone()
                assert row["count"] == 0
        assert await storage.get_setting("model_config") is None
        assert await storage.get_reset_generation() != "initial"
        assert await storage.ready()
        async with storage.pool.connection() as conn:
            row = await (await conn.execute("SELECT value FROM unrelated_data")).fetchone()
            assert row["value"] == "keep"
    finally:
        await storage.close()
