"""InMemoryContextStore: a dependency-free vector store for demos and tests.

Implements ``ContextStore`` with plain-Python cosine similarity over vectors from
the configured ``EmbeddingsClient``. It needs no Chroma and no native libraries,
which keeps the instant demo image small and its startup instant. Chroma remains
the persistent default; this is for the zero-infrastructure demo and CI.

Selected via ``context.vector_store.type: memory``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from tendwell.context.embeddings import EmbeddingsClient
from tendwell.interfaces.context_store import ContextStore, Document, RetrievedChunk


@dataclass
class _Entry:
    document: Document
    vector: list[float]
    norm: float


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


class InMemoryContextStore(ContextStore):
    """A ``ContextStore`` keeping embeddings in memory; no external dependency."""

    def __init__(self, embeddings: EmbeddingsClient) -> None:
        self._embeddings = embeddings
        self._entries: dict[str, _Entry] = {}

    async def upsert(self, documents: Iterable[Document]) -> None:
        docs = list(documents)
        if not docs:
            return
        vectors = await self._embeddings.embed([d.text for d in docs])
        for doc, vector in zip(docs, vectors, strict=False):
            norm = _dot(vector, vector) ** 0.5
            self._entries[doc.id] = _Entry(document=doc, vector=vector, norm=norm)

    async def retrieve(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        if not self._entries:
            return []
        query_vector = (await self._embeddings.embed([query]))[0]
        query_norm = _dot(query_vector, query_vector) ** 0.5
        if query_norm == 0.0:
            return []

        scored: list[tuple[float, _Entry]] = []
        for entry in self._entries.values():
            denom = entry.norm * query_norm
            score = _dot(entry.vector, query_vector) / denom if denom else 0.0
            scored.append((score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)

        return [
            RetrievedChunk(
                text=entry.document.text,
                score=score,
                document_id=entry.document.id,
                source=entry.document.source,
                metadata=dict(entry.document.metadata),
            )
            for score, entry in scored[:k]
        ]

    async def count(self) -> int:
        return len(self._entries)

    async def clear(self) -> None:
        self._entries.clear()
