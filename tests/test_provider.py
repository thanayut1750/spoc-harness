import json

import httpx
from langchain_core.messages import HumanMessage, ToolMessage
from openai import AsyncOpenAI

from org_harness.providers import ZaiChatModel


async def test_reasoning_is_roundtripped_with_tool_result():
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        message = {"role": "assistant", "content": "Complete", "reasoning_content": "opaque-data"}
        if len(requests) == 1:
            message.update(
                content=None,
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"query":"evidence"}'},
                    }
                ],
            )
        return httpx.Response(
            200,
            json={
                "id": "response",
                "object": "chat.completion",
                "created": 1,
                "model": "glm-5.3-flash",
                "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    client = AsyncOpenAI(
        api_key="test",
        base_url="https://model.invalid/v4",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    model = ZaiChatModel(async_client=client)
    first = await model.ainvoke([HumanMessage(content="Research")])
    assert first.tool_calls[0]["args"] == {"query": "evidence"}
    await model.ainvoke(
        [
            HumanMessage(content="Research"),
            first,
            ToolMessage(content="source", tool_call_id="call-1"),
        ]
    )
    assert requests[1]["messages"][1]["reasoning_content"] == "opaque-data"
    assert requests[1]["messages"][2]["tool_call_id"] == "call-1"
    assert requests[0]["reasoning_effort"] == "max"
    assert requests[0]["thinking"]["clear_thinking"] is False
    assert first.usage_metadata["total_tokens"] == 30
    await model.aclose()
