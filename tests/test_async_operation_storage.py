"""Background task discovery survives model compaction and database reopening."""

import pytest

from org_harness.storage import MemoryStorage, PostgresStorage


async def exercise_task_discovery(storage):
    first = await storage.create_run({"user_request": "Research two independent topics"})
    other = await storage.create_run({"user_request": "Separate mission"})
    for task, run_id, kind in (
        ("second", first["run_id"], "async_subagent"),
        ("first", first["run_id"], "async_subagent"),
        ("unrelated", other["run_id"], "async_subagent"),
        ("command", first["run_id"], "command"),
    ):
        await storage.begin_operation(run_id, task, kind, {"requirement": task})
    await storage.complete_operation(
        "second", {"state": "queued", "task_id": "second"}, status="pending"
    )
    await storage.complete_operation("first", {"state": "completed", "artifact_ids": ["proof"]})
    tasks = await storage.list_operations(first["run_id"], kind="async_subagent")
    assert [item["operation_id"] for item in tasks] == ["second", "first"]
    assert tasks[0]["status"] == "pending" and tasks[0]["result"]["state"] == "queued"
    assert tasks[1]["status"] == "done" and tasks[1]["result"]["artifact_ids"] == ["proof"]
    tasks[0]["request"]["requirement"] = "mutated caller copy"
    assert (await storage.get_operation("second"))["request"] == {"requirement": "second"}
    assert len(await storage.list_operations(first["run_id"])) == 3
    assert await storage.list_operations("missing-run", kind="async_subagent") == []
    # Background jobs are not falsely classified as uncertain external commands.
    assert [
        item["operation_id"] for item in await storage.uncertain_operations(first["run_id"])
    ] == ["command"]
    return first["run_id"]


async def test_memory_background_tasks_are_scoped_persisted_and_copy_safe():
    await exercise_task_discovery(MemoryStorage())


@pytest.mark.integration
async def test_postgres_background_tasks_survive_fresh_storage(postgres_url):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        run_id = await exercise_task_discovery(storage)
    finally:
        await storage.close()
    reopened = PostgresStorage(postgres_url)
    await reopened.open()
    try:
        tasks = await reopened.list_operations(run_id, kind="async_subagent")
        assert [item["operation_id"] for item in tasks] == ["second", "first"]
        assert tasks[0]["result"]["state"] == "queued"
        assert tasks[1]["result"]["artifact_ids"] == ["proof"]
    finally:
        await reopened.close()
