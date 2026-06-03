"""ContextStore and ContextLoader interfaces, plus their data types.

Knowledge context - runbooks, postmortems, topology, ownership, SLO notes - is
embedded into a vector store and retrieved by relevance at reasoning time. This
is distinct from live signal, which is pulled per query from data sources and
never stored.

A ``ContextStore`` owns embedding and retrieval; it is constructed with the
configured embeddings endpoint so that, by default, embedding happens against a
local model and nothing leaves the host. ``ContextLoader`` implementations feed
documents into the store; the first loader reads a directory of markdown.

The first concrete store is ``ChromaContextStore`` under ``tendwell.context``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Document:
    """A unit of knowledge context to be embedded and stored.

    ``id`` must be stable across reloads so re-indexing updates in place rather
    than duplicating. ``source`` records where the document came from (for
    example a file path or loader name) for provenance in findings.
    """

    id: str
    text: str
    source: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk returned from a relevance query, with its similarity score.

    ``score`` is higher-is-more-relevant, normalized by the implementation.
    """

    text: str
    score: float
    document_id: str
    source: str
    metadata: Mapping[str, object] = field(default_factory=dict)


class ContextStore(ABC):
    """Abstract embedded knowledge store.

    Implementations embed documents on ``upsert`` and return the most relevant
    chunks on ``retrieve``. Embedding and chunking strategy are implementation
    and config concerns; callers work only with ``Document`` and
    ``RetrievedChunk``.
    """

    @abstractmethod
    async def upsert(self, documents: Iterable[Document]) -> None:
        """Embed and store (or replace, by ``id``) the given documents."""

    @abstractmethod
    async def retrieve(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        """Return up to ``k`` chunks most relevant to ``query``."""

    @abstractmethod
    async def count(self) -> int:
        """Return the number of stored chunks."""

    async def clear(self) -> None:
        """Remove all stored documents. Default: not supported."""
        raise NotImplementedError

    async def close(self) -> None:
        """Release any held resources. Default: no-op."""
        return None


class ContextLoader(ABC):
    """Abstract producer of knowledge ``Document`` objects.

    A loader knows how to read a particular source (a markdown directory, a git
    repo of runbooks, and so on) and turn it into documents for a
    ``ContextStore``. The first implementation loads a directory of markdown.
    """

    #: Loader type name (from config ``type``).
    type: str

    @abstractmethod
    async def load(self) -> Sequence[Document]:
        """Read the source and return its documents."""
