"""OpenAICompatibleLLMBackend: one client for every OpenAI-compatible runtime.

Targets a configurable ``base_url`` so the same code covers Ollama, vLLM,
llama.cpp server, LocalAI, and a LiteLLM proxy. This class only performs a
single completion; the multi-step reasoning loop (native or ReAct) lives in
``tendwell.core.reasoning``. ``supports_native_tool_calling`` reflects the
config capability flag and selects which loop the agent uses.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from tendwell.config.models import LLMConfig
from tendwell.interfaces.llm import (
    CompletionResult,
    LLMBackend,
    Message,
    ToolCall,
    ToolSpec,
)


def _message_to_openai(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": str(message.role)}
    if message.content is not None:
        payload["content"] = message.content
    if message.name is not None:
        payload["name"] = message.name
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                },
            }
            for call in message.tool_calls
        ]
    return payload


def _tool_to_openai(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        },
    }


class OpenAICompatibleLLMBackend(LLMBackend):
    """A ``LLMBackend`` over any OpenAI-compatible chat completions endpoint."""

    def __init__(self, config: LLMConfig, api_key: str | None = None) -> None:
        from openai import AsyncOpenAI

        self.model = config.model
        self._params = dict(config.params)
        self._native = config.capabilities.native_tool_calling
        self._client = AsyncOpenAI(base_url=config.base_url, api_key=api_key or "not-needed")

    @property
    def supports_native_tool_calling(self) -> bool:
        return self._native

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        **params: object,
    ) -> CompletionResult:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_to_openai(m) for m in messages],
            **self._params,
            **params,
        }
        if tools and self._native:
            request["tools"] = [_tool_to_openai(t) for t in tools]
            request["tool_choice"] = "auto"

        response = await self._client.chat.completions.create(**request)
        choice = response.choices[0]
        message = choice.message

        tool_calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))

        usage: dict[str, int] = {}
        if response.usage is not None:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return CompletionResult(
            content=message.content,
            tool_calls=tuple(tool_calls),
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )
