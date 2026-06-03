"""Instant-tier demo: stub LLM, hash embeddings, in-memory store - no network.

The end-to-end test drives the real wiring from the actual examples/demo-instant
config with nothing injected, proving that `docker compose up` (which runs
exactly this) produces a real health report with no model and no external store.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tendwell.app import run_analysis
from tendwell.config import load_config
from tendwell.context.embeddings import FakeEmbeddings
from tendwell.context.memory_store import InMemoryContextStore
from tendwell.interfaces.context_store import Document
from tendwell.interfaces.output import Severity
from tendwell.llm.stub import StubLLMBackend

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTANT_CONFIG = REPO_ROOT / "examples" / "demo-instant.yaml"


async def test_stub_backend_returns_final_answer_without_tools() -> None:
    backend = StubLLMBackend()
    assert backend.supports_native_tool_calling is True
    result = await backend.complete([])
    assert result.tool_calls == ()
    assert result.content


async def test_memory_store_retrieves_relevant_chunk() -> None:
    store = InMemoryContextStore(FakeEmbeddings())
    await store.upsert(
        [
            Document(id="1", text="http error rate budget rollback deploy", source="err.md"),
            Document(id="2", text="p99 latency tail slow path contention", source="lat.md"),
        ]
    )
    assert await store.count() == 2
    chunks = await store.retrieve("error rate rollback", k=2)
    assert chunks[0].source == "err.md"
    assert chunks[0].score >= chunks[-1].score


async def test_empty_memory_store_returns_nothing() -> None:
    store = InMemoryContextStore(FakeEmbeddings())
    assert await store.retrieve("anything") == []


async def test_instant_config_produces_real_report_offline() -> None:
    # No llm/embeddings injected: the config's stub/hash/memory providers drive
    # everything. This is the docker compose instant tier.
    config = load_config(INSTANT_CONFIG)
    report = await run_analysis(config)
    assert report.overall is Severity.CRITICAL
    assert {b.metric for b in report.snapshot.breaches} == {"error_rate", "latency_p99"}
    # Real knowledge retrieval against the bundled corpus, grounded citations.
    assert report.citations
    assert all(c.source.endswith(".md") for c in report.citations)


def test_instant_config_is_local_first() -> None:
    from tendwell.config import egress_warnings

    config = load_config(INSTANT_CONFIG)
    assert egress_warnings(config) == []


@pytest.mark.parametrize(
    "path",
    [
        "examples/demo.yaml",
        "examples/demo-react.yaml",
        "examples/demo-actions.yaml",
        "examples/demo-instant.yaml",
    ],
)
def test_example_configs_load(path: str) -> None:
    load_config(REPO_ROOT / path)
