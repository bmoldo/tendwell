"""End-to-end agent tests with fakes: real wiring, no network, no model.

Runs the full stack (synthetic source, real Chroma store with fake embeddings,
the agent loop) through both the native and the ReAct-fallback tool paths, and
asserts they produce equivalent reports. This is the path CI exercises on every
build.
"""

from __future__ import annotations

from pathlib import Path

import tendwell.demo
from tendwell.app import run_analysis
from tendwell.config.models import TendwellConfig
from tendwell.context.embeddings import FakeEmbeddings
from tendwell.interfaces.output import Severity
from tendwell.llm.fake import FakeLLMBackend
from tests.conftest import text_response, tool_response

KNOWLEDGE = (Path(tendwell.demo.__file__).parent / "knowledge").as_posix()
FINAL = (
    "Both SLOs are breached. The error rate is well over budget and p99 latency "
    "is above the objective; see the error-rate runbook and latency postmortem."
)


def _config() -> TendwellConfig:
    return TendwellConfig.model_validate(
        {
            "data_sources": [
                {
                    "name": "demo",
                    "type": "synthetic",
                    "scenario": "degraded",
                    "seed": 7,
                    "queries": [{"id": "error_rate"}, {"id": "latency_p99"}],
                }
            ],
            "slos": [
                {
                    "name": "availability",
                    "metric": "error_rate",
                    "threshold": 0.01,
                    "direction": "below",
                },
                {
                    "name": "latency",
                    "metric": "latency_p99",
                    "threshold": 0.5,
                    "direction": "below",
                },
            ],
            "context": {
                "vector_store": {"type": "chroma", "path": ""},
                "loaders": [{"type": "markdown", "path": KNOWLEDGE}],
            },
        }
    )


def _native_backend() -> FakeLLMBackend:
    return FakeLLMBackend(
        responses=[tool_response("get_health_snapshot", {}), text_response(FINAL)],
        native_tool_calling=True,
    )


def _react_backend() -> FakeLLMBackend:
    return FakeLLMBackend(
        responses=[
            text_response("Thought: inspect\nAction: get_health_snapshot\nAction Input: {}"),
            text_response(f"Thought: conclude\nFinal Answer: {FINAL}"),
        ],
        native_tool_calling=False,
    )


async def test_native_path_reports_breach_with_citations() -> None:
    report = await run_analysis(_config(), llm=_native_backend(), embeddings=FakeEmbeddings())
    assert report.overall is Severity.CRITICAL
    assert {b.metric for b in report.snapshot.breaches} == {"error_rate", "latency_p99"}
    assert report.summary == FINAL
    assert report.citations
    # Citations come only from retrieved chunks; a model cannot invent them.
    assert all(c.source.endswith(".md") for c in report.citations)


async def test_native_and_react_paths_are_equivalent() -> None:
    native = await run_analysis(_config(), llm=_native_backend(), embeddings=FakeEmbeddings())
    react = await run_analysis(_config(), llm=_react_backend(), embeddings=FakeEmbeddings())
    assert native.overall is react.overall
    assert native.summary == react.summary
    assert {b.name for b in native.snapshot.breaches} == {b.name for b in react.snapshot.breaches}
    assert {c.source for c in native.citations} == {c.source for c in react.citations}


async def test_react_persistent_malformed_degrades_to_deterministic_summary() -> None:
    backend = FakeLLMBackend(
        responses=[text_response("no structure whatsoever, just prose")],
        native_tool_calling=False,
    )
    report = await run_analysis(_config(), llm=backend, embeddings=FakeEmbeddings())
    assert report.truncated is True
    # Even with a useless model, the deterministic facts still surface.
    assert "breached" in report.summary.lower()
    assert report.overall is Severity.CRITICAL
