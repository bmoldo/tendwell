"""Interface contract tests.

These verify the abstract base classes cannot be instantiated directly, that a
minimal concrete implementation satisfies each contract, and that the shared
data types behave as documented.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tendwell.interfaces import (
    ContextStore,
    DataSource,
    Document,
    Finding,
    LLMBackend,
    MetricSample,
    OutputSink,
    QueryResult,
    RetrievedChunk,
    Severity,
    SignalKind,
)


def test_abcs_cannot_be_instantiated() -> None:
    for cls in (DataSource, LLMBackend, ContextStore, OutputSink):
        with pytest.raises(TypeError):
            cls()  # type: ignore[abstract]


def test_query_result_latest_value() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    later = datetime(2026, 1, 1, 12, 5, tzinfo=UTC)
    result = QueryResult(
        query_id="error_rate",
        source="metrics",
        kind=SignalKind.METRIC,
        retrieved_at=later,
        samples=(
            MetricSample(timestamp=now, value=0.1),
            MetricSample(timestamp=later, value=0.4),
        ),
    )
    assert result.latest_value == 0.4

    empty = QueryResult(
        query_id="x",
        source="metrics",
        kind=SignalKind.METRIC,
        retrieved_at=later,
    )
    assert empty.latest_value is None


async def test_minimal_data_source_satisfies_contract() -> None:
    class StaticSource(DataSource):
        name = "static"

        async def query(self, query_id: str) -> QueryResult:
            return QueryResult(
                query_id=query_id,
                source=self.name,
                kind=SignalKind.STATE,
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            )

        async def query_all(self) -> list[QueryResult]:
            return [await self.query("only")]

        async def health_check(self) -> bool:
            return True

    source = StaticSource()
    assert await source.health_check() is True
    results = await source.query_all()
    assert results[0].query_id == "only"
    await source.close()  # default no-op


async def test_minimal_context_store_satisfies_contract() -> None:
    class MemoryStore(ContextStore):
        def __init__(self) -> None:
            self._docs: list[Document] = []

        async def upsert(self, documents) -> None:  # type: ignore[no-untyped-def]
            self._docs.extend(documents)

        async def retrieve(self, query: str, k: int = 5) -> list[RetrievedChunk]:
            return [
                RetrievedChunk(
                    text=d.text,
                    score=1.0,
                    document_id=d.id,
                    source=d.source,
                )
                for d in self._docs[:k]
            ]

        async def count(self) -> int:
            return len(self._docs)

    store = MemoryStore()
    await store.upsert([Document(id="1", text="runbook", source="md")])
    assert await store.count() == 1
    chunks = await store.retrieve("anything")
    assert chunks[0].document_id == "1"


def test_finding_severity_ordering() -> None:
    finding = Finding(
        id="f1",
        title="Error budget burn",
        summary="5xx rate above SLO",
        severity=Severity.CRITICAL,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        slo="availability",
    )
    assert finding.severity is Severity.CRITICAL
    assert finding.slo == "availability"
