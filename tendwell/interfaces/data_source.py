"""DataSource interface and its normalized result types.

A data source fetches live signal from an external system (metrics, logs,
state) and returns it in a normalized shape so the agent loop never has to
know which backend produced it. The first concrete implementation is
``PrometheusDataSource`` under ``tendwell.sources``.

Live signal is never persisted by Tendwell. It is pulled per query at
reasoning time and discarded; only knowledge context (see
``tendwell.interfaces.context_store``) is embedded and stored.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SignalKind(StrEnum):
    """The kind of signal a query returns."""

    METRIC = "metric"
    LOG = "log"
    STATE = "state"


@dataclass(frozen=True)
class MetricSample:
    """A single timestamped numeric sample with its label set."""

    timestamp: datetime
    value: float
    labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LogEntry:
    """A single timestamped log line with its label set."""

    timestamp: datetime
    message: str
    labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryResult:
    """Normalized result of a single data-source query.

    A result carries either metric samples or log entries depending on
    ``kind``. ``query_id`` matches the operator-defined query id from config so
    callers can correlate a result back to the SLO it informs.
    """

    query_id: str
    source: str
    kind: SignalKind
    retrieved_at: datetime
    samples: Sequence[MetricSample] = field(default_factory=tuple)
    logs: Sequence[LogEntry] = field(default_factory=tuple)
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def latest_value(self) -> float | None:
        """Value of the most recent metric sample, or ``None`` if there is none."""
        if not self.samples:
            return None
        return max(self.samples, key=lambda s: s.timestamp).value


class DataSource(ABC):
    """Abstract source of live production signal.

    Implementations are constructed from their adapter-specific config slice
    (``type`` selects the adapter; the rest is adapter-specific) and expose a
    small, normalized query surface. Implementations should be read-only: a
    data source observes, it never mutates the system it reads from.
    """

    #: Operator-assigned name of this source instance (from config ``name``).
    name: str

    @abstractmethod
    async def query(self, query_id: str) -> QueryResult:
        """Run the operator-defined query with the given id and normalize it.

        Raises ``KeyError`` if no query with ``query_id`` is configured.
        """

    @abstractmethod
    async def query_all(self) -> list[QueryResult]:
        """Run every query configured for this source and return all results."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return ``True`` if the underlying backend is reachable and healthy."""

    async def close(self) -> None:
        """Release any held resources (connections, clients). Default: no-op."""
        return None
