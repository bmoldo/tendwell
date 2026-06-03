"""Synthetic data source for zero-infrastructure evaluation and CI.

It generates deterministic metric series for the demo SLOs so the agent has real
signal to reason over with no Prometheus, no cloud, nothing external. A
``healthy`` scenario keeps every SLO in budget; a ``degraded`` scenario breaches
one so the agent has something to find and explain.

Generation is seeded, so CI assertions on observed values and SLO states are
stable across runs.
"""

from __future__ import annotations

import zlib
from datetime import UTC, datetime, timedelta
from random import Random

from tendwell.config.models import SyntheticSourceConfig
from tendwell.interfaces.data_source import (
    DataSource,
    MetricSample,
    QueryResult,
    SignalKind,
)

# Per-metric base values for each scenario. Defaults to a small healthy value
# for any metric id the demo does not specifically profile.
_PROFILES: dict[str, dict[str, float]] = {
    "error_rate": {"healthy": 0.002, "degraded": 0.06},
    "latency_p99": {"healthy": 0.18, "degraded": 0.95},
}
_DEFAULT_PROFILE = {"healthy": 0.05, "degraded": 0.05}

_SAMPLE_COUNT = 10
_SAMPLE_INTERVAL = timedelta(minutes=1)


def _stable_seed(seed: int, query_id: str) -> int:
    """Combine the configured seed with a stable hash of the query id."""
    return seed ^ zlib.crc32(query_id.encode("utf-8"))


class SyntheticDataSource(DataSource):
    """A ``DataSource`` that fabricates realistic, deterministic metric series."""

    def __init__(self, config: SyntheticSourceConfig) -> None:
        self.name = config.name
        self._scenario = config.scenario
        self._seed = config.seed
        self._query_ids = [q.id for q in config.queries]

    def _generate(self, query_id: str, anchor: datetime) -> list[MetricSample]:
        profile = _PROFILES.get(query_id, _DEFAULT_PROFILE)
        base = profile.get(self._scenario, profile["healthy"])
        rng = Random(_stable_seed(self._seed, query_id))
        samples: list[MetricSample] = []
        for i in range(_SAMPLE_COUNT):
            jitter = 1.0 + rng.uniform(-0.08, 0.08)
            value = max(0.0, base * jitter)
            ts = anchor - _SAMPLE_INTERVAL * (_SAMPLE_COUNT - 1 - i)
            samples.append(MetricSample(timestamp=ts, value=value, labels={}))
        return samples

    async def query(self, query_id: str) -> QueryResult:
        if query_id not in self._query_ids:
            raise KeyError(query_id)
        anchor = datetime.now(UTC)
        return QueryResult(
            query_id=query_id,
            source=self.name,
            kind=SignalKind.METRIC,
            retrieved_at=anchor,
            samples=tuple(self._generate(query_id, anchor)),
            metadata={"scenario": self._scenario, "synthetic": True},
        )

    async def query_all(self) -> list[QueryResult]:
        return [await self.query(q) for q in self._query_ids]

    async def health_check(self) -> bool:
        return True
