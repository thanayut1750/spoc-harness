"""Producer validation prevents Unicode data from crashing JSONB persistence."""

import json

import httpx
import pytest
from psycopg.errors import UntranslatableCharacter
from pydantic import ValidationError

from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.models import ActivityEvent, RunCreate
from org_harness.storage import MemoryStorage, PostgresStorage
from org_harness.text_safety import contains_invalid_json_text, require_json_text


@pytest.mark.parametrize(
    "value", ["\x00", "\ud800", "\udfff", {"\x00": "ok"}, [{"text": "a\ud800b"}]]
)
def test_invalid_text_is_rejected_recursively_without_input_echo(value):
    assert contains_invalid_json_text(value)
    with pytest.raises(ValueError, match="Text contains"):
        require_json_text(value)


def test_scalar_unicode_layout_and_literal_escapes_are_preserved():
    text = "พระพุทธศาสนา\n\t😀 café literal \\u0000 \\ud800"
    assert require_json_text(text) is text
    assert not contains_invalid_json_text(json.loads('"\\ud83d\\ude00"'))
    assert RunCreate(user_request=text).user_request == text
    event = ActivityEvent(
        event_id="unicode", agent_id="agent", activity="writing", data={"text": text}
    )
    assert event.data["text"] == text


def test_contract_validation_exception_itself_hides_private_values():
    with pytest.raises(ValidationError) as error:
        RunCreate(user_request="private mission\ud800")
    assert "private mission" not in str(error.value)
    assert "Text contains" in str(error.value)


@pytest.fixture
async def text_api(tmp_path):
    storage = MemoryStorage()
    app = create_app(Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path), storage)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, storage


@pytest.mark.parametrize("invalid", ["\x00", "\ud800", "\udfff"])
async def test_http_run_invalid_unicode_returns_safe_422_before_queuing(text_api, invalid):
    client, storage = text_api
    response = await client.post(
        "/api/runs",
        content=json.dumps({"user_request": "private mission" + invalid}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["body"]
    assert "private mission" not in response.text
    assert "input" not in detail[0] and "ctx" not in detail[0]
    assert await storage.list_runs() == []
    assert storage.jobs == {}


@pytest.mark.parametrize("key", [False, True])
async def test_nested_webhook_unicode_is_rejected_before_event_persistence(text_api, key):
    client, storage = text_api
    data = {"private\x00key": "value"} if key else {"nested": [{"value": "private\ud800"}]}
    response = await client.post(
        "/api/integrations/events",
        content=json.dumps(
            {"event_id": "test", "agent_id": "external", "activity": "reading", "data": data}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "private" not in response.text
    assert await storage.events_after() == []


async def test_notes_and_resume_context_reject_invalid_text_without_mutation(text_api):
    client, storage = text_api
    run = await storage.create_run({"user_request": "Preserved mission"})
    before = await storage.get_run(run["run_id"])
    for endpoint, payload in (
        ("notes", {"content": "private note\x00"}),
        (
            "resume",
            {"interrupt_id": "test", "action": "provide_context", "context": "private\ud800"},
        ),
    ):
        response = await client.post(
            f"/api/runs/{run['run_id']}/{endpoint}",
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert "private" not in response.text
    assert await storage.get_run(run["run_id"]) == before
    assert storage.notes == []


async def test_http_metadata_is_guarded_before_database_text_parameters(text_api):
    client, storage = text_api
    assert (await client.get("/api/runs/bad%00identifier")).status_code == 422
    assert (await client.get("/api/events?generation=bad%00generation")).status_code == 422
    assert (
        await client.post(
            "/api/runs",
            json={"user_request": "Valid mission"},
            headers={"Idempotency-Key": "bad\x00key"},
        )
    ).status_code == 422
    assert await storage.list_runs() == []


async def test_valid_unicode_request_is_persisted_without_normalization(text_api):
    client, storage = text_api
    text = "พระพุทธศาสนา 😀\n\tUse literal \\u0000 in the documentation."
    response = await client.post("/api/runs", json={"user_request": text})
    assert response.status_code == 202
    assert (await storage.get_run(response.json()["run_id"]))["user_request"] == text


async def test_postgres_keeps_valid_text_exact_and_does_not_mask_unguarded_storage_errors(
    postgres_url,
):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        text = "พระพุทธศาสนา 😀\n\tLiteral \\u0000"
        run = await storage.create_run(RunCreate(user_request=text).model_dump(mode="json"))
        assert (await storage.get_run(run["run_id"]))["user_request"] == text
        await storage.begin_operation(run["run_id"], "raw-operation", "tool", {"path": "source"})
        # The actual incident's JSONB error remains a real error if a future
        # producer bypasses its guard. Storage never mutates evidence to hide it.
        with pytest.raises(UntranslatableCharacter):
            await storage.complete_operation("raw-operation", {"content": "binary\x00data"})
        assert (await storage.get_operation("raw-operation"))["status"] == "pending"
    finally:
        await storage.close()
