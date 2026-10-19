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

from org_harness.config import Settings
from org_harness.models import ModelSelection
from org_harness.text_safety import contains_invalid_json_value


class ProviderResponseError(ValueError):
    """A malformed external response, distinct from an internal parsing defect."""


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
    timeout: float = 300
    max_tokens: int = 32768
    protocol: str = "zai"
    client: Any = Field(default=None, exclude=True, repr=False)
    async_client: Any = Field(default=None, exclude=True, repr=False)

    @property
    def _llm_type(self) -> str:
        return "zai-chat" if self.protocol == "zai" else f"{self.protocol}-chat"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "reasoning_effort": self.reasoning_effort}

    def _request(self, messages: list[BaseMessage], **kwargs: Any) -> dict[str, Any]:
        if contains_invalid_json_value([message.model_dump(mode="python") for message in messages]):
            raise ProviderResponseError("Model request contains invalid JSON values")
        allowed = {"tools", "tool_choice", "response_format", "temperature", "top_p"}
        encoded = [encode_message(message) for message in messages]
        if self.protocol != "zai":
            for message in encoded:
                message.pop("reasoning_content", None)
        request: dict[str, Any] = {
            "model": self.model,
            "messages": encoded,
        }
        if self.protocol == "zai":
            request.update(max_tokens=self.max_tokens, temperature=1, top_p=0.95)
            request["extra_body"] = {
                "reasoning_effort": self.reasoning_effort,
                "thinking": {"type": "enabled", "clear_thinking": False},
            }
            if self.reasoning_effort == "none":
                request["extra_body"] = {"thinking": {"type": "disabled"}}
        elif self.protocol == "openai":
            request["max_completion_tokens"] = self.max_tokens
            request["reasoning_effort"] = self.reasoning_effort
        else:
            request["max_tokens"] = self.max_tokens
            if self.reasoning_effort != "none":
                request["extra_body"] = {"reasoning_effort": self.reasoning_effort}
        request.update({key: value for key, value in kwargs.items() if key in allowed})
        if contains_invalid_json_value(request):
            raise ProviderResponseError("Model request contains invalid JSON values")
        return request

    def _result(self, response: Any) -> ChatResult:
        choices = getattr(response, "choices", None)
        if not isinstance(choices, (list, tuple)) or not choices:
            raise ProviderResponseError("Provider response has no completion choices")
        choice = choices[0]
        message = getattr(choice, "message", None)
        if message is None:
            raise ProviderResponseError("Provider response has no assistant message")
        content = getattr(message, "content", None)
        if content is not None and not isinstance(content, str):
            raise ProviderResponseError("Provider response has an invalid message content type")
        tool_calls = getattr(message, "tool_calls", None) or []
        if not isinstance(tool_calls, (list, tuple)):
            raise ProviderResponseError("Provider response has invalid tool calls")
        extra = {}
        if getattr(message, "reasoning_content", None) is not None:
            extra["reasoning_content"] = message.reasoning_content
        calls, invalid = [], []
        for call in tool_calls:
            function = getattr(call, "function", None)
            if not function or not all(
                isinstance(value, str)
                for value in (
                    getattr(call, "id", None),
                    getattr(function, "name", None),
                    getattr(function, "arguments", None),
                )
            ):
                raise ProviderResponseError("Provider response has an invalid function call")
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
        usage = getattr(response, "usage", None)
        metadata = None
        if usage:
            if not all(
                isinstance(value, int) and value >= 0
                for value in (
                    getattr(usage, "prompt_tokens", None),
                    getattr(usage, "completion_tokens", None),
                    getattr(usage, "total_tokens", None),
                )
            ):
                raise ProviderResponseError("Provider response has invalid token usage")
            metadata = {
                "input_tokens": usage.prompt_tokens,
                "output_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }
        message_values: dict[str, Any] = {
            "content": content or "",
            "additional_kwargs": extra,
            "tool_calls": calls,
            "invalid_tool_calls": invalid,
            "usage_metadata": metadata,
            "response_metadata": {
                "model_name": getattr(response, "model", self.model),
                "finish_reason": getattr(choice, "finish_reason", None),
            },
        }
        if contains_invalid_json_value(message_values):
            raise ProviderResponseError("Provider response contains invalid JSON values")
        ai_message = AIMessage(**message_values)
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


def create_model(settings: Settings, selection: dict | None = None) -> ZaiChatModel:
    from urllib.parse import urlsplit

    chosen = (
        ModelSelection.model_validate(selection)
        if selection
        else settings.default_model_selection()
    )
    settings.validate_model_selection(chosen)
    base_url, key, zai = settings.provider_connection(chosen.provider)
    protocol = (
        "zai"
        if zai
        else "openai"
        if urlsplit(base_url).hostname == "api.openai.com"
        else "compatible"
    )
    return ZaiChatModel(
        model=chosen.model,
        base_url=base_url,
        api_key=key,
        reasoning_effort=chosen.reasoning_effort,
        timeout=settings.model_timeout,
        max_tokens=settings.model_max_tokens,
        protocol=protocol,
    )
