"""Context tests: markdown loading/chunking and Chroma retrieval with fakes."""

from __future__ import annotations

from pathlib import Path

from tendwell.context.chroma_store import ChromaContextStore
from tendwell.context.embeddings import FakeEmbeddings
from tendwell.context.markdown_loader import MarkdownContextLoader

_ERROR_DOC = """# Error rate runbook

When the http error rate climbs above the budget, roll back the recent deploy.
"""

_LATENCY_DOC = """# Latency postmortem

The p99 latency regression came from a slow path taken by a fraction of traffic.
"""


def _write_corpus(root: Path) -> None:
    (root / "error.md").write_text(_ERROR_DOC, encoding="utf-8")
    (root / "latency.md").write_text(_LATENCY_DOC, encoding="utf-8")


async def test_markdown_loader_chunks_with_source_and_heading(tmp_path: Path) -> None:
    _write_corpus(tmp_path)
    loader = MarkdownContextLoader(str(tmp_path), chunk_size=200, chunk_overlap=20)
    docs = await loader.load()
    assert docs, "expected at least one chunk"
    sources = {d.source for d in docs}
    assert sources == {"error.md", "latency.md"}
    error_chunk = next(d for d in docs if d.source == "error.md")
    assert error_chunk.metadata.get("heading") == "Error rate runbook"
    # Stable ids: re-loading yields the same ids.
    again = await loader.load()
    assert {d.id for d in docs} == {d.id for d in again}


async def test_chroma_retrieval_finds_relevant_chunk(tmp_path: Path) -> None:
    _write_corpus(tmp_path)
    docs = await MarkdownContextLoader(str(tmp_path)).load()
    store = ChromaContextStore(FakeEmbeddings())
    await store.upsert(docs)
    assert await store.count() == len(docs)

    chunks = await store.retrieve("http error rate budget rollback", k=2)
    assert chunks
    # The most relevant chunk must be the error-rate runbook, and its source
    # attribution must be intact (the model cannot invent this).
    assert chunks[0].source == "error.md"
    assert chunks[0].score >= chunks[-1].score


async def test_chroma_empty_store_returns_nothing() -> None:
    store = ChromaContextStore(FakeEmbeddings())
    assert await store.retrieve("anything") == []
