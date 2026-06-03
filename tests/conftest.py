"""Shared test builders: offline fakes and small constructors."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from tendwell.config.models import SyntheticQuery, SyntheticSourceConfig
from tendwell.core.tools import ToolExecutor
from tendwell.core.types import HealthSnapshot, SLOState, SLOStatus
from tendwell.demo.synthetic import SyntheticDataSource
from tendwell.interfaces.context_store import ContextStore, Document, RetrievedChunk
from tendwell.interfaces.llm import CompletionResult, ToolCall

FIXED_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class FakeContextStore(ContextStore):
    """An in-memory store that returns planted chunks, for driver/agent tests."""

    def __init__(self, chunks: Sequence[RetrievedChunk] | None = None) -> None:
        self._chunks = list(chunks or [])
        self._docs: list[Document] = []

    async def upsert(self, documents: Iterable[Document]) -> None:
        self._docs.extend(documents)

    async def retrieve(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        return list(self._chunks[:k])

    async def count(self) -> int:
        return len(self._docs)


def text_response(text: str) -> CompletionResult:
    """A plain-text completion (ReAct path)."""
    return CompletionResult(content=text, finish_reason="stop")


def tool_response(name: str, arguments: dict[str, object], call_id: str = "1") -> CompletionResult:
    """A native tool-call completion."""
    return CompletionResult(
        content=None,
        tool_calls=(ToolCall(id=call_id, name=name, arguments=arguments),),
        finish_reason="tool_calls",
    )


def healthy_snapshot() -> HealthSnapshot:
    return HealthSnapshot(
        statuses=[
            SLOStatus(
                name="availability",
                metric="error_rate",
                state=SLOState.OK,
                threshold=0.01,
                direction="below",
                observed_value=0.002,
            )
        ],
        taken_at=FIXED_TIME,
    )


def synthetic_executor(scenario: str = "healthy") -> ToolExecutor:
    """A ToolExecutor wired to a synthetic source and an empty store."""
    config = SyntheticSourceConfig(
        name="demo",
        scenario=scenario,  # type: ignore[arg-type]
        seed=7,
        queries=[SyntheticQuery(id="error_rate"), SyntheticQuery(id="latency_p99")],
    )
    sources = {"demo": SyntheticDataSource(config)}
    return ToolExecutor(sources, FakeContextStore(), healthy_snapshot())
