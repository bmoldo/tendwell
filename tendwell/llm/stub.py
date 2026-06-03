"""A dependency-free stub LLM backend for the instant demo and offline eval.

It performs no network call and downloads no model. It returns immediately with
no tool calls, so the agent loop produces a real ``HealthReport`` whose facts
come entirely from the deterministic SLO snapshot and real knowledge retrieval -
only the narrative is a fixed note. This is what powers the instant tier of the
docker compose demo: see a real report in under a minute, then add a local model
for genuine model-driven narrative.

Selected via ``llm.provider: stub`` in config. The default provider is the real
OpenAI-compatible backend; this is for demos and CI only.
"""

from __future__ import annotations

from collections.abc import Sequence

from tendwell.interfaces.llm import CompletionResult, LLMBackend, Message, ToolSpec

STUB_NARRATIVE = (
    "Demo run using a stub model (no LLM configured). The SLO evaluation below is "
    "deterministic and real; configure a local model for narrative analysis and "
    "tool-driven drill-down."
)


class StubLLMBackend(LLMBackend):
    """A no-op backend that returns a fixed narrative and never calls tools."""

    def __init__(self, narrative: str = STUB_NARRATIVE, model: str = "stub") -> None:
        self.model = model
        self._narrative = narrative

    @property
    def supports_native_tool_calling(self) -> bool:
        # True so the agent uses the native driver, which returns our content as
        # the final answer in a single step (no tool calls, no ReAct parsing).
        return True

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        **params: object,
    ) -> CompletionResult:
        return CompletionResult(content=self._narrative, tool_calls=(), finish_reason="stop")
