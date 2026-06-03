# Add a data source

A data source fetches live production signal (metrics, logs, state) from an
external system and returns it in a normalized shape, so the agent loop never has
to know which backend produced it. Adding one means implementing a small
interface, normalizing into the shared types, defining a config model, and wiring
the adapter into the app.

Worked examples ship in the tree:

- `tendwell/sources/prometheus.py` -- PromQL instant queries.
- `tendwell/sources/loki.py` -- LogQL range queries normalized into `LogEntry`.
- `tendwell/sources/http_json.py` -- a numeric value pulled from a JSON endpoint
  via a dot-path, normalized into a `MetricSample`.

This guide walks a small example modeled on `http_json`.

## 1. Implement the interface

Subclass the abstract `DataSource` in `tendwell/interfaces/data_source.py`. Set
`self.name` and implement the query surface:

- `async def query(self, query_id: str) -> QueryResult` -- run one operator-defined
  query. Raise `KeyError` for an unknown query id.
- `async def query_all(self) -> list[QueryResult]` -- run every configured query.
- `async def health_check(self) -> bool` -- return `True` if the backend is
  reachable and healthy.
- `async def close(self)` -- optional; release any held resources. The default is
  a no-op.

A data source is read-only: it observes, it never mutates the system it reads.

## 2. Normalize into the shared types

Never leak backend-specific shapes above the interface. Map everything into the
shared types from `tendwell/interfaces/data_source.py`:

- `QueryResult(query_id, source, kind, retrieved_at, samples, logs, metadata)`,
  where `kind` is `SignalKind.METRIC`, `SignalKind.LOG`, or `SignalKind.STATE`.
- `MetricSample(timestamp, value, labels)` for numeric samples.
- `LogEntry(timestamp, message, labels)` for log lines.

`query_id` must match the operator-defined query id from config, so a result can
be correlated back to the SLO it informs.

## 3. Raise typed errors on failure

The adapter must not crash the run. On failure, raise one of the typed errors from
`tendwell/sources/errors.py`:

- `SourceUnreachable` -- the backend could not be reached (network, DNS, timeout).
- `SourceAuthError` -- the backend rejected the credentials.
- `QueryError` -- the backend rejected the query or returned an error payload.

The agent's snapshot builder catches these and degrades the affected SLO to
`unknown`, so a failing source never breaks the rest of the analysis.

## 4. Define the config model

Define a config model that subclasses `DataSourceConfig`
(`tendwell/config/models.py`) with a `type: Literal["yourtype"]` discriminator and
your adapter-specific fields, typically a list of queries.

Auth uses the shared `AuthConfig`: `auth.mode` is one of `none`, `bearer`, or
`basic`, and `auth.token_env` names the environment variable holding the token.
Read the token from that env var; never inline it.

```python
from typing import Literal

from pydantic import Field

from tendwell.config.models import DataSourceConfig, _Strict


class WidgetQuery(_Strict):
    """A named query against the widget endpoint."""

    id: str
    path: str = ""
    value_path: str


class WidgetSourceConfig(DataSourceConfig):
    """Config shape of the widget adapter."""

    type: Literal["widget"] = "widget"
    queries: list[WidgetQuery] = Field(default_factory=list)
```

## 5. Implement the adapter

A minimal adapter, modeled on `http_json`, fetches a JSON endpoint and extracts a
numeric value:

```python
from datetime import UTC, datetime

import httpx

from tendwell.interfaces.data_source import (
    DataSource,
    MetricSample,
    QueryResult,
    SignalKind,
)
from tendwell.sources.errors import QueryError, SourceAuthError, SourceUnreachable


class WidgetDataSource(DataSource):
    """A DataSource that reads a numeric metric from the widget endpoint."""

    def __init__(self, config: WidgetSourceConfig, token: str | None = None) -> None:
        if not config.endpoint:
            raise ValueError(f"widget source '{config.name}' requires an endpoint")
        self.name = config.name
        self._endpoint = config.endpoint.rstrip("/")
        self._queries = {q.id: q for q in config.queries}
        self._headers: dict[str, str] = {}
        if config.auth.mode == "bearer" and token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(timeout=10.0)

    async def query(self, query_id: str) -> QueryResult:
        if query_id not in self._queries:
            raise KeyError(query_id)
        spec = self._queries[query_id]
        retrieved_at = datetime.now(UTC)
        url = f"{self._endpoint}/{spec.path.lstrip('/')}" if spec.path else self._endpoint
        try:
            response = await self._client.get(url, headers=self._headers)
        except httpx.HTTPError as exc:
            raise SourceUnreachable(f"widget unreachable: {exc}") from exc
        if response.status_code in (401, 403):
            raise SourceAuthError(f"endpoint rejected credentials (status {response.status_code})")
        if response.status_code != 200:
            raise QueryError(f"endpoint returned status {response.status_code} for '{query_id}'")
        value = float(response.json()[spec.value_path])
        sample = MetricSample(timestamp=retrieved_at, value=value, labels={})
        return QueryResult(
            query_id=query_id,
            source=self.name,
            kind=SignalKind.METRIC,
            retrieved_at=retrieved_at,
            samples=(sample,),
        )

    async def query_all(self) -> list[QueryResult]:
        return [await self.query(q) for q in self._queries]

    async def health_check(self) -> bool:
        try:
            response = await self._client.get(self._endpoint, headers=self._headers)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def close(self) -> None:
        await self._client.aclose()
```

## 6. Register the adapter

Wire the adapter into `build_sources` in `tendwell/app.py` by adding an `elif`
branch for your `type`, with a lazy import so the dependency is only loaded when
the adapter is used:

```python
elif source_config.type == "widget":
    from tendwell.sources.widget import WidgetDataSource

    widget = WidgetSourceConfig.model_validate(raw)
    sources[widget.name] = WidgetDataSource(
        widget, token=resolve_secret(widget.auth.token_env)
    )
    query_ids = [q.id for q in widget.queries]
```

## 7. Add tests

New adapters need unit tests with mocked payloads -- no live backend. For HTTP
adapters use `httpx.MockTransport`. Cover at least:

- success: a valid payload normalizes into the expected `QueryResult`.
- empty: an endpoint with no usable data.
- error: a non-2xx response raises `QueryError`.
- auth failure: a 401 or 403 raises `SourceAuthError`.

Also confirm that an unknown `query_id` raises `KeyError`.
