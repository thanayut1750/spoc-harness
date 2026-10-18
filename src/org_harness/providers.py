"""Z.AI chat adapter that retains interleaved reasoning across tool turns.

Only public LangChain model extension points are used. Provider reasoning is kept
inside messages for protocol correctness, never projected as office activity.
"""

import json
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from openai import AsyncOpenAI, OpenAI
from pydantic import Field, SecretStr


def encode_message(message: BaseMessage) -> dict[str, Any]:
    role = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}.get(
        message.type, message.type
    )
    result: dict[str, Any] = {"role": role, "content": message.content}
    if isinstance(message, AIMessage):
        reasoning = message.additional_kwargs.get("reasoning_content")
        if reasoning is not None:
            result["reasoning_content"] = reasoning
        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call["args"])},
                }
                for call in message.tool_calls
            ]
    if isinstance(message, ToolMessage):
        result["tool_call_id"] = message.tool_call_id
    return result


class ZaiChatModel(BaseChatModel):
    model: str = "glm-5.3-flash"
    base_url: str = "https://api.z.ai/api/coding/paas/v4"
    api_key: SecretStr = Field(default=SecretStr(""), exclude=True)
    reasoning_effort: str = "max"
    timeout: float = 180
    max_tokens: int = 8192
    client: Any = Field(default=None, exclude=True, repr=False)
    async_client: Any = Field(default=None, exclude=True, repr=False)

    @property
    def _llm_type(self) -> str:
        return "zai-chat"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "reasoning_effort": self.reasoning_effort}

    def _request(self, messages: list[BaseMessage], **kwargs: Any) -> dict[str, Any]:
        allowed = {"tools", "tool_choice", "response_format", "temperature", "top_p"}
        request = {
            "model": self.model,
            "messages": [encode_message(message) for message in messages],
            "max_tokens": self.max_tokens,
            "temperature": 1,
            "top_p": 0.95,
            "extra_body": {
                "reasoning_effort": self.reasoning_effort,
                "thinking": {"type": "enabled", "clear_thinking": False},
            },
        }
        request.update({key: value for key, value in kwargs.items() if key in allowed})
        return request

    def _result(self, response: Any) -> ChatResult:
        choice = response.choices[0]
        message = choice.message
        extra = {}
        if getattr(message, "reasoning_content", None) is not None:
            extra["reasoning_content"] = message.reasoning_content
        calls, invalid = [], []
        for call in message.tool_calls or []:
            try:
                args = json.loads(call.function.arguments)
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be an object")
                calls.append({"id": call.id, "name": call.function.name, "args": args})
            except (ValueError, TypeError) as exc:
                invalid.append(
                    {
                        "id": call.id,
                        "name": call.function.name,
                        "args": call.function.arguments,
                        "error": str(exc),
                    }
                )
        usage = response.usage
        metadata = None
        if usage:
            metadata = {
                "input_tokens": usage.prompt_tokens,
                "output_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }
        ai_message = AIMessage(
            content=message.content or "",
            additional_kwargs=extra,
            tool_calls=calls,
            invalid_tool_calls=invalid,
            usage_metadata=metadata,
            response_metadata={"model_name": response.model, "finish_reason": choice.finish_reason},
        )
        return ChatResult(generations=[ChatGeneration(message=ai_message)])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.client is None:
            self.client = OpenAI(
                api_key=self.api_key.get_secret_value(),
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=0,
            )
        return self._result(
            self.client.chat.completions.create(**self._request(messages, **kwargs))
        )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.async_client is None:
            self.async_client = AsyncOpenAI(
                api_key=self.api_key.get_secret_value(),
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=0,
            )
        response = await self.async_client.chat.completions.create(
            **self._request(messages, **kwargs)
        )
        return self._result(response)

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Any:
        if tool_choice not in (None, "auto"):
            raise ValueError("Z.AI adapter supports automatic tool selection only")
        return self.bind(tools=[convert_to_openai_tool(tool) for tool in tools], tool_choice="auto")

    async def aclose(self) -> None:
        if self.async_client is not None:
            await self.async_client.close()
        if self.client is not None:
            self.client.close()
