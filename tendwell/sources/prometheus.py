"""PrometheusDataSource: the first real data-source adapter.

Executes operator-defined PromQL against the Prometheus HTTP API and normalizes
the response into the shared ``QueryResult`` / ``MetricSample`` types, so nothing
Prometheus-specific leaks above the interface. Failures raise typed errors; the
agent's snapshot builder catches them and degrades the affected SLO to
``unknown`` rather than crashing the run.

Config shape: ``PrometheusSourceConfig`` (``type: prometheus``) with an
``endpoint``, optional ``auth`` (``none`` / ``bearer`` / ``basic``), and a list
of ``{id, promql}`` queries. Credentials come from the environment only.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from tendwell.config.models import PrometheusSourceConfig
from tendwell.interfaces.data_source import (
    DataSource,
    MetricSample,
    QueryResult,
    SignalKind,
)


class DataSourceError(Exception):
    """Base class for data-source failures."""


class SourceUnreachable(DataSourceError):
    """The backend could not be reached (network, DNS, timeout)."""


class SourceAuthError(DataSourceError):
    """The backend rejected the credentials."""


class QueryError(DataSourceError):
    """The backend rejected the query or returned an error payload."""


def _parse_vector(data: dict[str, object], retrieved_at: datetime) -> list[MetricSample]:
    """Normalize an instant-vector or range-matrix result into samples."""
    result_type = data.get("resultType")
    series = data.get("result")
    if not isinstance(series, list):
        return []

    samples: list[MetricSample] = []
    for entry in series:
        if not isinstance(entry, dict):
            continue
        labels = {str(k): str(v) for k, v in (entry.get("metric") or {}).items()}
        if result_type == "matrix":
            points = entry.get("values") or []
        else:
            single = entry.get("value")
            points = [single] if single else []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                continue
            ts_raw, value_raw = point
            try:
                value = float(value_raw)
            except (TypeError, ValueError):
                continue
            samples.append(
                MetricSample(
                    timestamp=datetime.fromtimestamp(float(ts_raw), tz=UTC),
                    value=value,
                    labels=labels,
                )
            )
    return samples


class PrometheusDataSource(DataSource):
    """A ``DataSource`` backed by the Prometheus HTTP query API."""

    def __init__(
        self,
        config: PrometheusSourceConfig,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not config.endpoint:
            raise ValueError(f"prometheus source '{config.name}' requires an endpoint")
        self.name = config.name
        self._endpoint = config.endpoint.rstrip("/")
        self._queries = {q.id: q.promql for q in config.queries}
        self._timeout = timeout

        headers: dict[str, str] = {}
        auth: httpx.Auth | None = None
        if config.auth.mode == "bearer" and token:
            headers["Authorization"] = f"Bearer {token}"
        elif config.auth.mode == "basic" and token:
            username, _, password = token.partition(":")
            auth = httpx.BasicAuth(username, password)
        self._headers = headers
        self._auth = auth

        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def query(self, query_id: str) -> QueryResult:
        if query_id not in self._queries:
            raise KeyError(query_id)
        promql = self._queries[query_id]
        retrieved_at = datetime.now(UTC)
        try:
            response = await self._client.get(
                f"{self._endpoint}/api/v1/query",
                params={"query": promql},
                headers=self._headers,
                auth=self._auth,
            )
        except httpx.HTTPError as exc:
            raise SourceUnreachable(f"prometheus unreachable: {exc}") from exc

        if response.status_code in (401, 403):
            raise SourceAuthError(
                f"prometheus rejected credentials (status {response.status_code})"
            )
        if response.status_code != 200:
            raise QueryError(
                f"prometheus returned status {response.status_code} for query '{query_id}'"
            )

        payload = response.json()
        if payload.get("status") != "success":
            raise QueryError(
                f"prometheus query '{query_id}' failed: {payload.get('error', 'unknown error')}"
            )

        samples = _parse_vector(payload.get("data") or {}, retrieved_at)
        return QueryResult(
            query_id=query_id,
            source=self.name,
            kind=SignalKind.METRIC,
            retrieved_at=retrieved_at,
            samples=tuple(samples),
            metadata={"promql": promql},
        )

    async def query_all(self) -> list[QueryResult]:
        return [await self.query(q) for q in self._queries]

    async def health_check(self) -> bool:
        try:
            response = await self._client.get(
                f"{self._endpoint}/-/healthy",
                headers=self._headers,
                auth=self._auth,
            )
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
