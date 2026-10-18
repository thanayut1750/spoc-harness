"""Malformed wire data is a typed provider failure, never an accidental lookup crash."""

from types import SimpleNamespace as Obj

import pytest

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
