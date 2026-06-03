"""PrometheusDataSource tests against mocked HTTP payloads (no live Prometheus)."""

from __future__ import annotations

import httpx
import pytest

from tendwell.config.models import (
    AuthConfig,
    PrometheusQuery,
    PrometheusSourceConfig,
)
from tendwell.sources.prometheus import (
    PrometheusDataSource,
    QueryError,
    SourceAuthError,
    SourceUnreachable,
)

_SUCCESS = {
    "status": "success",
    "data": {
        "resultType": "vector",
        "result": [
            {"metric": {"job": "api"}, "value": [1700000000, "0.042"]},
        ],
    },
}

_EMPTY = {"status": "success", "data": {"resultType": "vector", "result": []}}

_ERROR = {"status": "error", "errorType": "bad_data", "error": "parse error"}


def _source(handler: object, mode: str = "none", token: str | None = None) -> PrometheusDataSource:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    client = httpx.AsyncClient(transport=transport)
    config = PrometheusSourceConfig(
        name="metrics",
        endpoint="http://prometheus.local:9090",
        auth=AuthConfig(mode=mode),  # type: ignore[arg-type]
        queries=[PrometheusQuery(id="error_rate", promql="up")],
    )
    return PrometheusDataSource(config, token=token, client=client)


async def test_success_vector_is_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_SUCCESS)

    source = _source(handler)
    result = await source.query("error_rate")
    assert result.latest_value == 0.042
    assert result.samples[0].labels == {"job": "api"}
    assert result.metadata["promql"] == "up"


async def test_empty_result_has_no_value() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_EMPTY)

    source = _source(handler)
    result = await source.query("error_rate")
    assert result.latest_value is None


async def test_error_payload_raises_query_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ERROR)

    source = _source(handler)
    with pytest.raises(QueryError):
        await source.query("error_rate")


async def test_auth_failure_raises_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"status": "error"})

    source = _source(handler, mode="bearer", token="secret")
    with pytest.raises(SourceAuthError):
        await source.query("error_rate")


async def test_unreachable_raises_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    source = _source(handler)
    with pytest.raises(SourceUnreachable):
        await source.query("error_rate")


async def test_unknown_query_raises_keyerror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_SUCCESS)

    source = _source(handler)
    with pytest.raises(KeyError):
        await source.query("not_configured")


async def test_bearer_token_sets_auth_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json=_SUCCESS)

    source = _source(handler, mode="bearer", token="secret-token")
    await source.query("error_rate")
    assert seen["auth"] == "Bearer secret-token"
