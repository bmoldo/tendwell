"""ChromaContextStore: the default local-first knowledge store.

Embeds documents with the configured ``EmbeddingsClient`` and persists them in
Chroma. When no path is given the store is in-memory, which is what tests use.
Embedding is always done by our client and passed to Chroma explicitly, so the
embedding endpoint (and the local-first guarantee) is the one from config.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast
from uuid import uuid4

from tendwell.context.embeddings import EmbeddingsClient
from tendwell.interfaces.context_store import (
    ContextStore,
    Document,
    RetrievedChunk,
)

_COSINE = {"hnsw:space": "cosine"}


def _scalar_metadata(document: Document) -> dict[str, str | int | float | bool]:
    """Chroma only stores scalar metadata; keep source plus scalar extras."""
    meta: dict[str, str | int | float | bool] = {"source": document.source}
    for key, value in document.metadata.items():
        if isinstance(value, str | int | float | bool):
            meta[key] = value
    return meta


class ChromaContextStore(ContextStore):
    """A ``ContextStore`` backed by Chroma with externally-computed embeddings."""

    def __init__(
        self,
        embeddings: EmbeddingsClient,
        path: str | None = None,
        collection_name: str = "tendwell_knowledge",
    ) -> None:
        import chromadb

        self._embeddings = embeddings
        if path:
            self._client = chromadb.PersistentClient(path=path)
            self._collection_name = collection_name
        else:
            # Chroma's in-memory client shares state across instances in one
            # process, so give each in-memory store its own collection to keep
            # them isolated (this is what tests rely on).
            self._client = chromadb.EphemeralClient()
            self._collection_name = f"{collection_name}_{uuid4().hex}"
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name, metadata=_COSINE
        )

    async def upsert(self, documents: Iterable[Document]) -> None:
        docs = list(documents)
        if not docs:
            return
        vectors = await self._embeddings.embed([d.text for d in docs])
        self._collection.upsert(
            ids=[d.id for d in docs],
            embeddings=cast(Any, vectors),
            documents=[d.text for d in docs],
            metadatas=cast(Any, [_scalar_metadata(d) for d in docs]),
        )

    async def retrieve(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        if self._collection.count() == 0:
            return []
        query_vector = (await self._embeddings.embed([query]))[0]
        result = self._collection.query(
            query_embeddings=cast(Any, [query_vector]),
            n_results=k,
            include=cast(Any, ["documents", "metadatas", "distances"]),
        )
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        chunks: list[RetrievedChunk] = []
        for doc_id, text, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=False
        ):
            meta = dict(metadata or {})
            source = str(meta.pop("source", "unknown"))
            chunks.append(
                RetrievedChunk(
                    text=text or "",
                    score=1.0 - float(distance),
                    document_id=str(doc_id),
                    source=source,
                    metadata=meta,
                )
            )
        return chunks

    async def count(self) -> int:
        return int(self._collection.count())

    async def clear(self) -> None:
        self._client.delete_collection(self._collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name, metadata=_COSINE
        )
