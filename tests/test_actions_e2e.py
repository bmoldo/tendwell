"""End-to-end action path: model proposes, human gates, executor runs.

Exercises the full propose -> validate -> approve -> execute -> audit cycle
through the real agent and surface with fakes, including a partial-failure case.
Also asserts the default read-only posture: with no surface, the model cannot
even propose.
"""

from __future__ import annotations

from pathlib import Path

import tendwell.demo
from tendwell.actions.types import ActionState, TargetStatus
from tendwell.app import run_analysis
from tendwell.config.models import TendwellConfig
from tendwell.context.embeddings import FakeEmbeddings
from tendwell.llm.fake import FakeLLMBackend
from tests.action_helpers import ScriptedApprovalGate, make_surface, restart_action
from tests.conftest import text_response, tool_response

KNOWLEDGE = (Path(tendwell.demo.__file__).parent / "knowledge").as_posix()


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
            ],
            "context": {
                "vector_store": {"type": "chroma", "path": ""},
                "loaders": [{"type": "markdown", "path": KNOWLEDGE}],
            },
        }
    )


def _proposing_backend() -> FakeLLMBackend:
    return FakeLLMBackend(
        responses=[
            tool_response(
                "propose_action",
                {
                    "action": "restart_service",
                    "targets": ["api", "worker"],
                    "reason": "error rate is over budget",
                    "parameters": {},
                },
            ),
            text_response("Proposed a restart of api and worker for human approval."),
        ],
        native_tool_calling=True,
    )


async def test_full_action_cycle_with_partial_failure() -> None:
    executor_statuses = {"api": TargetStatus.SUCCESS, "worker": TargetStatus.FAILURE}
    from tendwell.actions.executor import FakeActionExecutor

    surface, audit = make_surface(
        executor=FakeActionExecutor(statuses=executor_statuses),
        gate=ScriptedApprovalGate(True),
        actions=[restart_action()],
    )

    report = await run_analysis(
        _config(),
        llm=_proposing_backend(),
        embeddings=FakeEmbeddings(),
        action_surface=surface,
    )

    # The model proposed; nothing executed during analysis.
    assert len(report.proposals) == 1
    assert report.proposals[0].action == "restart_service"

    # Execution is a separate, human-gated phase.
    results = await surface.process_pending()
    assert len(results) == 1
    assert results[0].state is ActionState.PARTIAL
    statuses = {o.target: o.status for o in results[0].target_outcomes}
    assert statuses == {"api": TargetStatus.SUCCESS, "worker": TargetStatus.FAILURE}
    assert audit.verify()


async def test_read_only_default_cannot_propose() -> None:
    # No action surface: the propose_action tool does not exist, so a model that
    # tries to call it gets an unknown-tool observation and produces no proposals.
    backend = _proposing_backend()
    report = await run_analysis(_config(), llm=backend, embeddings=FakeEmbeddings())
    assert report.proposals == ()
