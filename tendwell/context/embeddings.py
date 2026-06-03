"""Embeddings clients used by the context store.

The store depends on the small ``EmbeddingsClient`` interface, not on any
provider, so embedding can be faked in tests with no model and no network.
``OpenAICompatibleEmbeddings`` is the real, local-first default;
``FakeEmbeddings`` is deterministic and offline.
"""

from __future__ import annotations

import re
import zlib
from abc import ABC, abstractmethod
from collections.abc import Sequence

from tendwell.config.models import EmbeddingsConfig

_TOKEN = re.compile(r"[a-z0-9]+")


class EmbeddingsClient(ABC):
    """Turns text into vectors. The only embedding surface the store needs."""

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


class FakeEmbeddings(EmbeddingsClient):
    """Deterministic, offline embeddings for tests.

    Uses a hashing bag-of-words vectorizer so that texts sharing words land near
    each other: a query about "error rate" retrieves the error-rate runbook
    without any model. Not meaningful for production, only for testing retrieval
    plumbing.
    """

    def __init__(self, dimension: int = 64) -> None:
        self.dimension = dimension

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        for token in _TOKEN.findall(text.lower()):
            idx = zlib.crc32(token.encode("utf-8")) % self.dimension
            vec[idx] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class OpenAICompatibleEmbeddings(EmbeddingsClient):
    """Embeddings via any OpenAI-compatible endpoint (local model by default)."""

    def __init__(self, config: EmbeddingsConfig, api_key: str | None = None) -> None:
        from openai import AsyncOpenAI

        self._model = config.model
        # A non-empty placeholder key keeps local servers that ignore auth happy.
        self._client = AsyncOpenAI(base_url=config.base_url, api_key=api_key or "not-needed")

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(model=self._model, input=list(texts))
        return [list(item.embedding) for item in response.data]
