"""The action surface test matrix.

Covers validation, the approval gate, execution including partial failure, the
audit lifecycle and tamper-evidence, containment (kill switch, rate limit,
breaker, reserved targets), and dry-run. Everything runs with fakes; no real
infrastructure.
"""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import ValidationError

from tendwell.actions.audit import AuditEventType, AuditLog, verify_chain
from tendwell.actions.executor import FakeActionExecutor
from tendwell.actions.guards import ActionGuards, CircuitBreaker, KillSwitch, RateLimiter
from tendwell.actions.types import ActionState, TargetStatus, ValidationCode
from tendwell.config.models import (
    ActionConfig,
    CircuitBreakerConfig,
    RateLimitConfig,
)
from tests.action_helpers import (
    ScriptedApprovalGate,
    make_surface,
    permissive_guards,
    restart_action,
)


# ---------------------------------------------------------------------------
# Validation (deterministic, pre-human)
# ---------------------------------------------------------------------------
async def test_unknown_action_rejected_before_approval() -> None:
    executor = FakeActionExecutor()
    gate = ScriptedApprovalGate(True)
    surface, _ = make_surface(executor=executor, gate=gate)
    proposal, outcome = surface.propose("delete_everything", ["api"], {}, "because")
    assert proposal is None
    assert outcome.code is ValidationCode.UNKNOWN_ACTION
    assert gate.calls == 0
    assert executor.calls == []


async def test_schema_invalid_rejected() -> None:
    surface, _ = make_surface()
    # graceful must be boolean
    proposal, outcome = surface.propose("restart_service", ["api"], {"graceful": "yes"}, "x")
    assert proposal is None
    assert outcome.code is ValidationCode.SCHEMA_INVALID


async def test_unknown_argument_rejected() -> None:
    surface, _ = make_surface()
    proposal, outcome = surface.propose("restart_service", ["api"], {"force": True}, "x")
    assert proposal is None
    assert outcome.code is ValidationCode.SCHEMA_INVALID


async def test_out_of_scope_rejected() -> None:
    surface, _ = make_surface()
    proposal, outcome = surface.propose("restart_service", ["database"], {}, "x")
    assert proposal is None
    assert outcome.code is ValidationCode.OUT_OF_SCOPE


async def test_too_many_targets_rejected() -> None:
    surface, _ = make_surface(actions=[restart_action(max_targets=1)])
    proposal, outcome = surface.propose("restart_service", ["api", "worker"], {}, "x")
    assert proposal is None
    assert outcome.code is ValidationCode.TOO_MANY_TARGETS


async def test_no_targets_rejected() -> None:
    surface, _ = make_surface()
    proposal, outcome = surface.propose("restart_service", [], {}, "x")
    assert proposal is None
    assert outcome.code is ValidationCode.NO_TARGETS


# ---------------------------------------------------------------------------
# Containment in config: reserved names are structurally untargetable
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name",
    ["edit_config", "modify_audit_log", "rotate_credentials", "self_approve", "read_secret"],
)
def test_reserved_action_names_rejected_at_config(name: str) -> None:
    with pytest.raises(ValidationError):
        ActionConfig.model_validate({"name": name})


def test_auto_approval_rejected_at_config() -> None:
    with pytest.raises(ValidationError):
        ActionConfig.model_validate({"name": "restart_service", "require_approval": False})


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------
async def test_rejected_proposal_never_executes() -> None:
    executor = FakeActionExecutor()
    gate = ScriptedApprovalGate(False)
    surface, _ = make_surface(executor=executor, gate=gate)
    proposal, _ = surface.propose("restart_service", ["api"], {}, "x")
    assert proposal is not None
    result = await surface.process(proposal)
    assert result.state is ActionState.REJECTED_BY_HUMAN
    assert executor.calls == []


async def test_timed_out_proposal_never_executes() -> None:
    executor = FakeActionExecutor()
    gate = ScriptedApprovalGate(False, timed_out=True)
    surface, _ = make_surface(executor=executor, gate=gate)
    proposal, _ = surface.propose("restart_service", ["api"], {}, "x")
    assert proposal is not None
    result = await surface.process(proposal)
    assert result.state is ActionState.APPROVAL_TIMEOUT
    assert executor.calls == []


def test_model_has_no_approve_or_execute_tool() -> None:
    # The read-only tool executor with an action surface exposes propose_action
    # and nothing that approves or executes. No self-approval path exists.
    from tendwell.core.tools import ToolExecutor
    from tests.conftest import FakeContextStore, healthy_snapshot

    surface, _ = make_surface()
    executor = ToolExecutor({}, FakeContextStore(), healthy_snapshot(), action_surface=surface)
    names = {spec.name for spec in executor.tool_specs()}
    assert "propose_action" in names
    assert "approve" not in names
    assert "execute" not in names
    assert not any("approve" in n or "execute" in n for n in names)


# ---------------------------------------------------------------------------
# Execution and partial failure
# ---------------------------------------------------------------------------
async def test_execution_success() -> None:
    surface, _ = make_surface(gate=ScriptedApprovalGate(True))
    proposal, _ = surface.propose("restart_service", ["api", "worker"], {}, "x")
    assert proposal is not None
    result = await surface.process(proposal)
    assert result.state is ActionState.EXECUTED
    assert all(o.status is TargetStatus.SUCCESS for o in result.target_outcomes)
    assert result.approver == "alice"


async def test_full_failure() -> None:
    executor = FakeActionExecutor(default_status=TargetStatus.FAILURE)
    surface, _ = make_surface(executor=executor)
    proposal, _ = surface.propose("restart_service", ["api", "worker"], {}, "x")
    assert proposal is not None
    result = await surface.process(proposal)
    assert result.state is ActionState.FAILED


async def test_partial_failure_records_per_target() -> None:
    executor = FakeActionExecutor(
        statuses={"api": TargetStatus.SUCCESS, "worker": TargetStatus.FAILURE}
    )
    surface, _ = make_surface(executor=executor)
    proposal, _ = surface.propose("restart_service", ["api", "worker"], {}, "x")
    assert proposal is not None
    result = await surface.process(proposal)
    assert result.state is ActionState.PARTIAL
    statuses = {o.target: o.status for o in result.target_outcomes}
    assert statuses == {"api": TargetStatus.SUCCESS, "worker": TargetStatus.FAILURE}


async def test_executor_exception_becomes_failure_not_crash() -> None:
    executor = FakeActionExecutor(raises={"api"})
    surface, _ = make_surface(executor=executor)
    proposal, _ = surface.propose("restart_service", ["api"], {}, "x")
    assert proposal is not None
    result = await surface.process(proposal)
    assert result.state is ActionState.FAILED
    assert result.target_outcomes[0].status is TargetStatus.FAILURE


async def test_idempotent_action_retries_once_on_failure() -> None:
    # An idempotent action retries a failing target; a non-idempotent one does not.
    executor = FakeActionExecutor(default_status=TargetStatus.FAILURE)
    surface, _ = make_surface(executor=executor, actions=[restart_action(idempotent=True)])
    proposal, _ = surface.propose("restart_service", ["api"], {}, "x")
    assert proposal is not None
    await surface.process(proposal)
    assert executor.calls == [("api", False), ("api", False)]


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------
async def test_dry_run_plans_without_approval_or_mutation() -> None:
    executor = FakeActionExecutor()
    gate = ScriptedApprovalGate(True)
    surface, _ = make_surface(executor=executor, gate=gate)
    proposal, _ = surface.propose("restart_service", ["api"], {}, "x", dry_run=True)
    assert proposal is not None
    result = await surface.process(proposal)
    assert result.state is ActionState.DRY_RUN
    assert gate.calls == 0
    assert executor.calls == [("api", True)]
    assert result.target_outcomes[0].status is TargetStatus.PLANNED


# ---------------------------------------------------------------------------
# Containment: kill switch, rate limit, circuit breaker
# ---------------------------------------------------------------------------
async def test_kill_switch_blocks_validation() -> None:
    guards = permissive_guards()
    guards.kill_switch.engage()
    surface, _ = make_surface(guards=guards)
    proposal, outcome = surface.propose("restart_service", ["api"], {}, "x")
    assert proposal is None
    assert outcome.code is ValidationCode.KILL_SWITCH


async def test_kill_switch_halts_pending_after_validation() -> None:
    guards = permissive_guards()
    executor = FakeActionExecutor()
    surface, _ = make_surface(guards=guards, executor=executor)
    proposal, _ = surface.propose("restart_service", ["api"], {}, "x")
    assert proposal is not None
    guards.kill_switch.engage()  # engaged after validation, before processing
    result = await surface.process(proposal)
    assert result.state is ActionState.KILLED
    assert executor.calls == []


async def test_rate_limit_rejects_after_window_full() -> None:
    guards = ActionGuards(
        kill_switch=KillSwitch(),
        rate_limiter=RateLimiter(
            RateLimitConfig(max_actions=1, window_seconds=10_000), lambda: 0.0
        ),
        circuit_breaker=CircuitBreaker(CircuitBreakerConfig(failure_threshold=100)),
    )
    surface, _ = make_surface(guards=guards)
    first, _ = surface.propose("restart_service", ["api"], {}, "x")
    assert first is not None
    await surface.process(first)  # consumes the one slot
    second, outcome = surface.propose("restart_service", ["worker"], {}, "x")
    assert second is None
    assert outcome.code is ValidationCode.RATE_LIMITED


async def test_circuit_breaker_opens_after_failures() -> None:
    guards = ActionGuards(
        kill_switch=KillSwitch(),
        rate_limiter=RateLimiter(
            RateLimitConfig(max_actions=100, window_seconds=10_000), lambda: 0.0
        ),
        circuit_breaker=CircuitBreaker(CircuitBreakerConfig(failure_threshold=1)),
    )
    executor = FakeActionExecutor(default_status=TargetStatus.FAILURE)
    surface, _ = make_surface(guards=guards, executor=executor)
    first, _ = surface.propose("restart_service", ["api"], {}, "x")
    assert first is not None
    await surface.process(first)  # fails -> trips breaker
    second, outcome = surface.propose("restart_service", ["worker"], {}, "x")
    assert second is None
    assert outcome.code is ValidationCode.BREAKER_OPEN


# ---------------------------------------------------------------------------
# Audit lifecycle and tamper-evidence
# ---------------------------------------------------------------------------
async def test_audit_records_full_lifecycle_and_verifies() -> None:
    executor = FakeActionExecutor(
        statuses={"api": TargetStatus.SUCCESS, "worker": TargetStatus.FAILURE}
    )
    surface, audit = make_surface(executor=executor)
    proposal, _ = surface.propose("restart_service", ["api", "worker"], {}, "x")
    assert proposal is not None
    await surface.process(proposal)

    types = [e.event_type for e in audit.events_for(proposal.id)]
    assert AuditEventType.PROPOSAL_CREATED in types
    assert AuditEventType.VALIDATION_PASSED in types
    assert AuditEventType.APPROVAL_GRANTED in types
    assert AuditEventType.EXECUTION_STARTED in types
    assert types.count(AuditEventType.TARGET_OUTCOME) == 2
    assert AuditEventType.EXECUTION_COMPLETED in types
    assert audit.verify()

    # Attempted vs completed is reconstructable from the completion event.
    completed = next(e for e in audit.events if e.event_type is AuditEventType.EXECUTION_COMPLETED)
    assert completed.details["attempted"] == ["api", "worker"]
    assert completed.details["succeeded"] == ["api"]
    assert completed.details["failed"] == ["worker"]


async def test_audit_detects_tampered_entry() -> None:
    surface, audit = make_surface()
    proposal, _ = surface.propose("restart_service", ["api"], {}, "x")
    assert proposal is not None
    await surface.process(proposal)
    assert audit.verify()

    events = list(audit.events)
    tampered = list(events)
    tampered[1] = dataclasses.replace(tampered[1], details={"action": "something_else"})
    assert verify_chain(tampered) is False


async def test_audit_detects_missing_entry() -> None:
    surface, audit = make_surface()
    proposal, _ = surface.propose("restart_service", ["api"], {}, "x")
    assert proposal is not None
    await surface.process(proposal)
    events = list(audit.events)
    assert verify_chain(events[:1] + events[2:]) is False


def test_audit_log_persists_append_only(tmp_path: object) -> None:
    path = tmp_path / "audit.jsonl"  # type: ignore[operator]
    log = AuditLog(path=path)
    log.append(AuditEventType.PROPOSAL_CREATED, "p0", {"action": "restart_service"})
    log.append(AuditEventType.VALIDATION_PASSED, "p0", {})
    contents = path.read_text().strip().splitlines()  # type: ignore[attr-defined]
    assert len(contents) == 2
    assert log.verify()


# ---------------------------------------------------------------------------
# No auto-chaining
# ---------------------------------------------------------------------------
async def test_processing_does_not_create_new_proposals() -> None:
    surface, _ = make_surface()
    surface.propose("restart_service", ["api"], {}, "x")
    surface.propose("restart_service", ["worker"], {}, "x")
    results = await surface.process_pending()
    assert len(results) == 2
    # The queue is drained and execution produced no further proposals.
    assert list(surface.pending) == []
