"""A scripted LLM backend for offline unit and end-to-end tests.

No network, no model. It returns pre-built completions in order; once the script
is exhausted it repeats the last entry, which is what the step-cap and
graceful-degradation tests rely on (the model "never finishes").
"""

from __future__ import annotations

from collections.abc import Sequence

from tendwell.interfaces.llm import CompletionResult, LLMBackend, Message, ToolSpec


class FakeLLMBackend(LLMBackend):
    """A ``LLMBackend`` implementation driven by a fixed list of responses."""

    def __init__(
        self,
        responses: Sequence[CompletionResult],
        native_tool_calling: bool = True,
        model: str = "fake",
    ) -> None:
        if not responses:
            raise ValueError("FakeLLMBackend needs at least one scripted response")
        self.model = model
        self._responses = list(responses)
        self._native = native_tool_calling
        self._index = 0
        #: Recorded (messages, tools) for each call, for test assertions.
        self.calls: list[tuple[Sequence[Message], Sequence[ToolSpec] | None]] = []

    @property
    def supports_native_tool_calling(self) -> bool:
        return self._native

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        **params: object,
    ) -> CompletionResult:
        self.calls.append((list(messages), tools))
        response = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return response
