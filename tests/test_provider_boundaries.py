"""Malformed wire data is a typed provider failure, never an accidental lookup crash."""

import json
from types import SimpleNamespace as Obj

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from org_harness.providers import ProviderResponseError, ZaiChatModel


def response(message=None, **kwargs):
    return Obj(
        choices=[
            Obj(message=message or Obj(content="answer", tool_calls=[]), finish_reason="stop")
        ],
        usage=None,
        model="test",
        **kwargs,
    )


@pytest.mark.parametrize(
    "data",
    [
        Obj(choices=[]),
        Obj(choices=None),
        Obj(),
        Obj(choices=[Obj()]),
        response(Obj(content={}, tool_calls=[])),
        response(Obj(content="", tool_calls=[Obj(function=None)])),
        response(
            Obj(content="", tool_calls=[Obj(id="one", function=Obj(name="read", arguments=None))])
        ),
    ],
)
def test_missing_provider_fields_raise_narrow_typed_error(data):
    with pytest.raises(ProviderResponseError):
        ZaiChatModel()._result(data)


def test_invalid_usage_is_typed_and_does_not_echo_provider_payload():
    data = response()
    data.usage = Obj(prompt_tokens="secret body", completion_tokens=1, total_tokens=2)
    with pytest.raises(ProviderResponseError) as error:
        ZaiChatModel()._result(data)
    assert "secret body" not in str(error.value)


def test_bad_tool_json_stays_recoverable_inside_assistant_message():
    data = response(
        Obj(content="", tool_calls=[Obj(id="one", function=Obj(name="read", arguments="not JSON"))])
    )
    message = ZaiChatModel()._result(data).generations[0].message
    assert message.invalid_tool_calls[0]["name"] == "read"


def test_valid_answer_without_optional_usage_still_works():
    assert ZaiChatModel()._result(response()).generations[0].text == "answer"


@pytest.mark.parametrize("invalid", ["\x00", "\ud800", "\udfff"])
@pytest.mark.parametrize(
    "field", ["content", "reasoning", "argument", "argument_key", "call_id", "model"]
)
def test_provider_unicode_is_validated_before_messages_or_tool_execution(invalid, field):
    private = "private provider payload" + invalid
    message = Obj(content="Answer", reasoning_content="private reasoning", tool_calls=[])
    data = response(message)
    if field == "content":
        message.content = private
    elif field == "reasoning":
        message.reasoning_content = private
    elif field == "model":
        data.model = private
    else:
        args = {private: "value"} if field == "argument_key" else {"content": private}
        message.tool_calls = [
            Obj(
                id=private if field == "call_id" else "call",
                function=Obj(name="write_file", arguments=json.dumps(args)),
            )
        ]
    with pytest.raises(ProviderResponseError) as error:
        ZaiChatModel()._result(data)
    assert "private provider payload" not in str(error.value)
    assert "private reasoning" not in str(error.value)


def test_provider_keeps_valid_unicode_and_literal_escapes_exactly():
    text = "พระพุทธศาสนา 😀\n\tLiteral \\u0000"
    message = Obj(
        content=text,
        reasoning_content=text,
        tool_calls=[
            Obj(id="call", function=Obj(name="write_file", arguments=json.dumps({"content": text})))
        ],
    )
    result = ZaiChatModel()._result(response(message)).generations[0].message
    assert result.content == result.additional_kwargs["reasoning_content"] == text
    assert result.tool_calls[0]["args"] == {"content": text}


@pytest.mark.parametrize("tool_call", [False, True])
def test_model_request_guard_covers_raw_text_and_nested_tool_arguments(tool_call):
    message = (
        AIMessage(
            content="",
            tool_calls=[{"id": "call", "name": "write_file", "args": {"content": "private\x00"}}],
        )
        if tool_call
        else HumanMessage(content="private\ud800")
    )
    with pytest.raises(ProviderResponseError) as error:
        ZaiChatModel()._request([message])
    assert "private" not in str(error.value)
