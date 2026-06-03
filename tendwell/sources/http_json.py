"""HttpJsonDataSource: generic JSON-over-HTTP metrics adapter.

For the long tail of systems that expose a JSON endpoint but speak no standard
metrics protocol. Each query fetches a URL and extracts a numeric value via a
configured dot-path (``data.0.value``), mapping it to a single ``MetricSample``.
Failures raise the shared typed errors so the SLO degrades to ``unknown``.

Config shape: ``HttpJsonSourceConfig`` (``type: http_json``) with an
``endpoint``, optional ``auth``, and ``{id, path, value_path}`` queries.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from tendwell.config.models import HttpJsonSourceConfig
from tendwell.interfaces.data_source import (
    DataSource,
    MetricSample,
    QueryResult,
    SignalKind,
)
from tendwell.sources.errors import QueryError, SourceAuthError, SourceUnreachable


def extract_value(payload: object, value_path: str) -> float:
    """Walk a dot-path into a JSON payload and return a numeric leaf.

    Raises ``QueryError`` if the path is missing or the leaf is not numeric.
    """
    current = payload
    for segment in value_path.split("."):
        if isinstance(current, list):
            try:
                index = int(segment)
            except ValueError as exc:
                raise QueryError(f"value_path segment {segment!r} is not a list index") from exc
            try:
                current = current[index]
            except IndexError as exc:
                raise QueryError(f"value_path index {index} out of range") from exc
        elif isinstance(current, dict):
            if segment not in current:
                raise QueryError(f"value_path key {segment!r} not found")
            current = current[segment]
        else:
            raise QueryError(f"value_path {value_path!r} does not resolve to a value")
    if isinstance(current, bool) or not isinstance(current, int | float):
        raise QueryError(f"value at {value_path!r} is not numeric")
    return float(current)


class HttpJsonDataSource(DataSource):
    """A ``DataSource`` that reads a numeric metric from a JSON endpoint."""

    def __init__(
        self,
        config: HttpJsonSourceConfig,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not config.endpoint:
            raise ValueError(f"http_json source '{config.name}' requires an endpoint")
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
        url = f"{self._endpoint}/{spec.path.lstrip('/')}" if spec.path else self._endpoint
        try:
            response = await self._client.get(url, headers=self._headers, auth=self._auth)
        except httpx.HTTPError as exc:
            raise SourceUnreachable(f"http_json unreachable: {exc}") from exc

        if response.status_code in (401, 403):
            raise SourceAuthError(f"endpoint rejected credentials (status {response.status_code})")
        if response.status_code != 200:
            raise QueryError(
                f"endpoint returned status {response.status_code} for query '{query_id}'"
            )

        value = extract_value(response.json(), spec.value_path)
        sample = MetricSample(timestamp=retrieved_at, value=value, labels={})
        return QueryResult(
            query_id=query_id,
            source=self.name,
            kind=SignalKind.METRIC,
            retrieved_at=retrieved_at,
            samples=(sample,),
            metadata={"value_path": spec.value_path},
        )

    async def query_all(self) -> list[QueryResult]:
        return [await self.query(q) for q in self._queries]

    async def health_check(self) -> bool:
        try:
            response = await self._client.get(
                self._endpoint, headers=self._headers, auth=self._auth
            )
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
