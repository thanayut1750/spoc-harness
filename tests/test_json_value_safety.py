"""Non-finite external numbers never reach persistent JSON or execute host tools."""

import json
import math
from types import SimpleNamespace as Obj

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from psycopg.errors import InvalidTextRepresentation
from pydantic import ValidationError

from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.models import ActivityEvent, EscalationSignal, RunCreate
from org_harness.providers import ProviderResponseError, ZaiChatModel
from org_harness.storage import MemoryStorage, PostgresStorage, fingerprint
from org_harness.text_safety import (
    contains_invalid_json_text,
    contains_invalid_json_value,
    require_json_text,
)
from org_harness.tools import Artifacts, HostTools, json_safe_display


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_json_values_are_rejected_recursively_without_sensitive_echo(number):
    value = {"private input": [{"measurement": number}]}
    assert contains_invalid_json_value(value)
    assert not contains_invalid_json_text(value)
    assert contains_invalid_json_value({number: "key"})
    with pytest.raises(ValueError, match="numbers must be finite"):
        require_json_text(value)
    with pytest.raises(ValidationError) as caught:
        ActivityEvent(event_id="test", agent_id="external", activity="reading", data=value)
    assert "private input" not in str(caught.value)


def test_finite_values_and_valid_unicode_remain_exact():
    value = {"measurements": [0, -2.5, 1e308, True, None], "text": "😀\n\tliteral NaN"}
    assert not contains_invalid_json_value(value)
    assert require_json_text(value) is value
    assert json_safe_display(value) is value


async def _exercise_http_boundary(storage, tmp_path):
    app = create_app(Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path), storage)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for literal in ("NaN", "Infinity", "-Infinity", "1e999"):
            response = await client.post(
                "/api/integrations/events",
                content=(
                    '{"event_id":"unsafe","agent_id":"external","activity":"reading",'
                    '"data":{"private source":{"measurement":' + literal + "}}}"
                ).encode(),
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 422
            assert "private source" not in response.text
            assert "input" not in response.json()["detail"][0]
            response = await client.post(
                "/api/runs",
                content=(
                    '{"user_request":"private mission","limits":{"worker_timeout":' + literal + "}}"
                ).encode(),
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 422
            assert "private mission" not in response.text
        assert await storage.events_after() == []
        assert await storage.list_runs() == []


async def _exercise_journal_boundary(storage, tmp_path):
    run = await storage.create_run(
        RunCreate(user_request="Test finite JSON").model_dump(mode="json")
    )
    artifacts = Artifacts(storage, tmp_path, run["run_id"])

    async def emit(*args, **kwargs):
        pass

    host = HostTools(
        storage,
        artifacts,
        run,
        kr_id="kr-1",
        department="engineering",
        epoch=0,
        role="backend_coder",
        emit=emit,
    )
    effects = []

    async def never_execute():
        effects.append("executed")
        (host.workspace / "never.txt").write_text("unsafe effect")
        return {"result": "never"}

    for index, number in enumerate((float("nan"), float("inf"), -float("inf"))):
        request = {"arguments": {"private argument": [number]}}
        for kind in ("tool", "command"):
            call_id = f"nonfinite-{index}-{kind}"
            result = await host.journal(
                call_id, "run_mission_tool", request, never_execute, kind=kind
            )
            assert result["error"] == "ExpectedToolInputError"
            assert "private argument" not in result["detail"]
            assert (
                await host.journal(call_id, "run_mission_tool", request, never_execute, kind=kind)
                == result
            )
            operation = await storage.get_operation(host.operation_id(call_id, "run_mission_tool"))
            assert operation["request"] == {
                "invalid_input": True,
                "request_fingerprint": fingerprint(request),
            }
            assert operation["status"] == "done" and operation["kind"] == "invalid_input"
        recorded = await host.record_research(
            f"nonfinite-research-{index}", "reader", request, never_execute
        )
        assert recorded["error"] == "ExpectedToolInputError"
    assert effects == []
    assert not (host.workspace / "never.txt").exists()
    assert await storage.list_artifacts(run["run_id"]) == []
    assert await storage.uncertain_operations(run["run_id"]) == []
    with pytest.raises(EscalationSignal) as conflict:
        await host.journal(
            "nonfinite-0-tool", "run_mission_tool", {"arguments": [float("inf")]}, never_execute
        )
    assert conflict.value.kind == "operation_conflict"

    async def external_result():
        return {"label": "source\n😀", "numbers": [float("nan"), float("inf"), -float("inf")]}

    raw = await external_result()
    expected = {"label": "source\\n\\ud83d\\ude00", "numbers": ["NaN", "Infinity", "-Infinity"]}
    displayed = await host.journal("nonfinite-output", "reader", {}, external_result)
    assert displayed == {**expected, "display_encoding": "json-string-escape"}
    json.dumps(displayed, allow_nan=False)
    assert not contains_invalid_json_value(displayed)
    recorded = await host.record_research("nonfinite-source", "reader", {}, external_result)
    assert recorded["result"] == expected
    assert recorded["display_encoding"] == "json-string-escape"
    json.dumps(recorded, allow_nan=False)
    _, original = await artifacts.read(recorded["artifact_id"], limit=None)
    restored = json.loads(original)
    assert restored["label"] == raw["label"]
    assert math.isnan(restored["numbers"][0])
    assert restored["numbers"][1:] == raw["numbers"][1:]


async def test_memory_ingress_rejects_nonfinite_inputs_and_displays_external_outputs(tmp_path):
    await _exercise_http_boundary(MemoryStorage(), tmp_path / "api")
    await _exercise_journal_boundary(MemoryStorage(), tmp_path / "tools")


@pytest.mark.integration
async def test_postgres_ingress_rejects_nonfinite_before_jsonb_without_hiding_raw_storage_errors(
    tmp_path, postgres_url
):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        await _exercise_http_boundary(storage, tmp_path / "api")
        await _exercise_journal_boundary(storage, tmp_path / "tools")
        run = (await storage.list_runs())[0]
        await storage.begin_operation(run["run_id"], "unguarded-json", "tool", {})
        with pytest.raises(InvalidTextRepresentation):
            await storage.complete_operation("unguarded-json", {"number": float("nan")})
        assert (await storage.get_operation("unguarded-json"))["status"] == "pending"
    finally:
        await storage.close()


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_provider_rejects_nonfinite_tool_arguments_before_checkpointed_messages(literal):
    response = Obj(
        choices=[
            Obj(
                message=Obj(
                    content="",
                    tool_calls=[
                        Obj(
                            id="call",
                            function=Obj(name="tool", arguments='{"private":' + literal + "}"),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=None,
        model="test",
    )
    with pytest.raises(ProviderResponseError) as caught:
        ZaiChatModel()._result(response)
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("boundary", ["arguments", "kwargs", "reasoning"])
def test_provider_request_rejects_nested_nonfinite_numbers(boundary):
    message = HumanMessage(content="valid request")
    kwargs = {}
    if boundary == "arguments":
        message = AIMessage(
            content="",
            tool_calls=[{"id": "call", "name": "tool", "args": {"value": float("nan")}}],
        )
    elif boundary == "kwargs":
        kwargs = {"temperature": float("inf")}
    else:
        message = AIMessage(content="", additional_kwargs={"reasoning_content": float("nan")})
    with pytest.raises(ProviderResponseError):
        ZaiChatModel()._request([message], **kwargs)
