"""HttpJsonDataSource tests against mocked payloads (no live endpoint)."""

from __future__ import annotations

import httpx
import pytest

from tendwell.config.models import AuthConfig, HttpJsonQuery, HttpJsonSourceConfig
from tendwell.sources.errors import QueryError, SourceAuthError, SourceUnreachable
from tendwell.sources.http_json import HttpJsonDataSource, extract_value


def _source(handler: object, value_path: str = "data.0.value") -> HttpJsonDataSource:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    config = HttpJsonSourceConfig(
        name="custom",
        endpoint="http://service.local/metrics",
        auth=AuthConfig(mode="none"),
        queries=[HttpJsonQuery(id="qps", path="qps", value_path=value_path)],
    )
    return HttpJsonDataSource(config, client=client)


def test_extract_value_walks_dicts_and_lists() -> None:
    payload = {"data": [{"value": 12.5}]}
    assert extract_value(payload, "data.0.value") == 12.5


def test_extract_value_missing_key_raises() -> None:
    with pytest.raises(QueryError):
        extract_value({"data": {}}, "data.value")


def test_extract_value_non_numeric_raises() -> None:
    with pytest.raises(QueryError):
        extract_value({"value": "high"}, "value")


def test_extract_value_rejects_bool() -> None:
    with pytest.raises(QueryError):
        extract_value({"value": True}, "value")


async def test_success_maps_to_metric_sample() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"value": 42.0}]})

    source = _source(handler)
    result = await source.query("qps")
    assert result.latest_value == 42.0


async def test_missing_path_degrades_via_query_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    source = _source(handler)
    with pytest.raises(QueryError):
        await source.query("qps")


async def test_auth_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with pytest.raises(SourceAuthError):
        await _source(handler).query("qps")


async def test_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(SourceUnreachable):
        await _source(handler).query("qps")
