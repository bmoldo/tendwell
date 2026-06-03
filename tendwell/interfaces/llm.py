"""LLMBackend interface and its message / tool-calling types.

The backend wraps an OpenAI-compatible chat completions endpoint. A single
client implementation therefore covers Ollama, vLLM, llama.cpp server,
LocalAI, and a LiteLLM proxy; the runtime is selected purely by ``base_url``
in config and is never hardcoded.

Small local models are inconsistent at native tool calling. The backend
declares its capability via config (``capabilities.native_tool_calling``); when
native calling is unavailable the concrete implementation falls back to a
prompt-based ReAct loop with strict output parsing. That fallback is an
implementation detail of ``tendwell.llm``; this interface only exposes the
capability flag and a uniform completion call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    """Chat message roles, matching the OpenAI-compatible schema."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class ToolSpec:
    """Declaration of a tool the model may call.

    ``parameters`` is a JSON Schema object describing the tool's arguments.
    """

    name: str
    description: str
    parameters: Mapping[str, object]


@dataclass(frozen=True)
class ToolCall:
    """A single tool invocation requested by the model."""

    id: str
    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class Message:
    """A single chat message.

    ``tool_calls`` is populated on assistant messages that request tools;
    ``tool_call_id`` links a tool-result message back to its originating call.
    """

    role: Role
    content: str | None = None
    name: str | None = None
    tool_calls: Sequence[ToolCall] = field(default_factory=tuple)
    tool_call_id: str | None = None


@dataclass(frozen=True)
class CompletionResult:
    """Outcome of a single completion call.

    Exactly one of ``content`` or ``tool_calls`` is the meaningful payload,
    determined by ``finish_reason`` ("stop" vs "tool_calls").
    """

    content: str | None
    tool_calls: Sequence[ToolCall] = field(default_factory=tuple)
    finish_reason: str = "stop"
    usage: Mapping[str, int] = field(default_factory=dict)


class LLMBackend(ABC):
    """Abstract reasoning engine behind an OpenAI-compatible endpoint."""

    #: Model identifier this backend was configured with.
    model: str

    @property
    @abstractmethod
    def supports_native_tool_calling(self) -> bool:
        """Whether the backend uses native tool calling (vs the ReAct fallback)."""

    @abstractmethod
    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        **params: object,
    ) -> CompletionResult:
        """Produce one completion for ``messages``.

        When ``tools`` is provided the model may respond with tool calls.
        ``params`` overrides per-call generation parameters (temperature, etc.)
        on top of the configured defaults.
        """
