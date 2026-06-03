"""LokiDataSource: logs adapter mapping LogQL range queries to LogEntry.

Normalizes Loki's stream/value shape into the shared ``LogEntry`` type so
nothing Loki-specific leaks above the interface. Failures raise the shared typed
errors; the snapshot builder degrades the affected SLO to ``unknown``.

Config shape: ``LokiSourceConfig`` (``type: loki``) with an ``endpoint``,
optional ``auth``, and ``{id, logql, limit, range_seconds}`` queries.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from tendwell.config.models import LokiSourceConfig
from tendwell.interfaces.data_source import (
    DataSource,
    LogEntry,
    QueryResult,
    SignalKind,
)
from tendwell.sources.errors import QueryError, SourceAuthError, SourceUnreachable


def _parse_streams(data: dict[str, object]) -> list[LogEntry]:
    result = data.get("result")
    if not isinstance(result, list):
        return []
    entries: list[LogEntry] = []
    for stream in result:
        if not isinstance(stream, dict):
            continue
        labels = {str(k): str(v) for k, v in (stream.get("stream") or {}).items()}
        for value in stream.get("values") or []:
            if not isinstance(value, list) or len(value) != 2:
                continue
            ts_ns, line = value
            try:
                timestamp = datetime.fromtimestamp(int(ts_ns) / 1e9, tz=UTC)
            except (TypeError, ValueError):
                continue
            entries.append(LogEntry(timestamp=timestamp, message=str(line), labels=labels))
    return entries


class LokiDataSource(DataSource):
    """A ``DataSource`` backed by the Loki HTTP query_range API."""

    def __init__(
        self,
        config: LokiSourceConfig,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not config.endpoint:
            raise ValueError(f"loki source '{config.name}' requires an endpoint")
        self.name = config.name
        self._endpoint = config.endpoint.rstrip("/")
        self._queries = {q.id: q for q in config.queries}

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
        spec = self._queries[query_id]
        retrieved_at = datetime.now(UTC)
        start = retrieved_at - timedelta(seconds=spec.range_seconds)
        params = {
            "query": spec.logql,
            "limit": str(spec.limit),
            "start": str(int(start.timestamp() * 1e9)),
            "end": str(int(retrieved_at.timestamp() * 1e9)),
        }
        try:
            response = await self._client.get(
                f"{self._endpoint}/loki/api/v1/query_range",
                params=params,
                headers=self._headers,
                auth=self._auth,
            )
        except httpx.HTTPError as exc:
            raise SourceUnreachable(f"loki unreachable: {exc}") from exc

        if response.status_code in (401, 403):
            raise SourceAuthError(f"loki rejected credentials (status {response.status_code})")
        if response.status_code != 200:
            raise QueryError(f"loki returned status {response.status_code} for query '{query_id}'")

        payload = response.json()
        if payload.get("status") != "success":
            raise QueryError(f"loki query '{query_id}' failed")

        entries = _parse_streams(payload.get("data") or {})
        return QueryResult(
            query_id=query_id,
            source=self.name,
            kind=SignalKind.LOG,
            retrieved_at=retrieved_at,
            logs=tuple(entries),
            metadata={"logql": spec.logql, "count": len(entries)},
        )

    async def query_all(self) -> list[QueryResult]:
        return [await self.query(q) for q in self._queries]

    async def health_check(self) -> bool:
        try:
            response = await self._client.get(
                f"{self._endpoint}/ready", headers=self._headers, auth=self._auth
            )
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
