"""Synthetic data source: determinism and scenario behavior."""

from __future__ import annotations

import pytest

from tendwell.config.models import SyntheticQuery, SyntheticSourceConfig
from tendwell.demo.synthetic import SyntheticDataSource


def _source(scenario: str) -> SyntheticDataSource:
    config = SyntheticSourceConfig(
        name="demo",
        scenario=scenario,  # type: ignore[arg-type]
        seed=7,
        queries=[SyntheticQuery(id="error_rate"), SyntheticQuery(id="latency_p99")],
    )
    return SyntheticDataSource(config)


async def test_healthy_scenario_stays_in_budget() -> None:
    source = _source("healthy")
    error_rate = await source.query("error_rate")
    latency = await source.query("latency_p99")
    assert error_rate.latest_value is not None and error_rate.latest_value < 0.01
    assert latency.latest_value is not None and latency.latest_value < 0.5


async def test_degraded_scenario_breaches() -> None:
    source = _source("degraded")
    error_rate = await source.query("error_rate")
    latency = await source.query("latency_p99")
    assert error_rate.latest_value is not None and error_rate.latest_value > 0.01
    assert latency.latest_value is not None and latency.latest_value > 0.5


async def test_deterministic_for_same_seed() -> None:
    a = await _source("degraded").query("error_rate")
    b = await _source("degraded").query("error_rate")
    assert [s.value for s in a.samples] == [s.value for s in b.samples]


async def test_unknown_query_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        await _source("healthy").query("does_not_exist")


async def test_query_all_covers_configured_queries() -> None:
    results = await _source("healthy").query_all()
    assert {r.query_id for r in results} == {"error_rate", "latency_p99"}
