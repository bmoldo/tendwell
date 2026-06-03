"""LokiDataSource tests against mocked payloads (no live Loki)."""

from __future__ import annotations

import httpx
import pytest

from tendwell.config.models import AuthConfig, LokiQuery, LokiSourceConfig
from tendwell.interfaces.data_source import SignalKind
from tendwell.sources.errors import QueryError, SourceAuthError, SourceUnreachable
from tendwell.sources.loki import LokiDataSource

_SUCCESS = {
    "status": "success",
    "data": {
        "resultType": "streams",
        "result": [
            {
                "stream": {"level": "error", "app": "api"},
                "values": [
                    ["1700000000000000000", "connection reset"],
                    ["1700000001000000000", "timeout talking to dependency"],
                ],
            }
        ],
    },
}

_EMPTY = {"status": "success", "data": {"resultType": "streams", "result": []}}


def _source(handler: object, mode: str = "none", token: str | None = None) -> LokiDataSource:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    config = LokiSourceConfig(
        name="logs",
        endpoint="http://loki.local:3100",
        auth=AuthConfig(mode=mode),  # type: ignore[arg-type]
        queries=[LokiQuery(id="errors", logql='{app="api"} |= "error"')],
    )
    return LokiDataSource(config, token=token, client=client)


async def test_success_streams_normalized_to_logs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_SUCCESS)

    source = _source(handler)
    result = await source.query("errors")
    assert result.kind is SignalKind.LOG
    assert len(result.logs) == 2
    assert result.logs[0].message == "connection reset"
    assert result.logs[0].labels == {"level": "error", "app": "api"}


async def test_empty_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_EMPTY)

    source = _source(handler)
    result = await source.query("errors")
    assert result.logs == ()


async def test_error_status_raises_query_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    source = _source(handler)
    with pytest.raises(QueryError):
        await source.query("errors")


async def test_auth_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    source = _source(handler, mode="bearer", token="t")
    with pytest.raises(SourceAuthError):
        await source.query("errors")


async def test_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    source = _source(handler)
    with pytest.raises(SourceUnreachable):
        await source.query("errors")


async def test_unknown_query_raises_keyerror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_SUCCESS)

    with pytest.raises(KeyError):
        await _source(handler).query("missing")
