"""Builders and a scripted approval gate for the action tests."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

from tendwell.actions.allowlist import ActionAllowlist
from tendwell.actions.approval import ApprovalGate
from tendwell.actions.audit import AuditLog
from tendwell.actions.executor import ActionExecutor, FakeActionExecutor
from tendwell.actions.guards import ActionGuards, CircuitBreaker, KillSwitch, RateLimiter
from tendwell.actions.pipeline import GatedActionSurface
from tendwell.actions.types import ActionProposal, ApprovalDecision
from tendwell.config.models import (
    ActionConfig,
    ActionParamSpec,
    CircuitBreakerConfig,
    RateLimitConfig,
)

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


class ScriptedApprovalGate(ApprovalGate):
    """Returns a fixed decision; records whether it was consulted."""

    def __init__(self, approved: bool, approver: str = "alice", timed_out: bool = False) -> None:
        self._approved = approved
        self._approver = approver
        self._timed_out = timed_out
        self.calls = 0

    async def decide(self, proposal: ActionProposal) -> ApprovalDecision:
        self.calls += 1
        return ApprovalDecision(
            approved=self._approved,
            approver=self._approver,
            decided_at=FIXED,
            reason="scripted",
            timed_out=self._timed_out,
        )


def restart_action(**overrides: object) -> ActionConfig:
    base: dict[str, object] = {
        "name": "restart_service",
        "scope": ["api", "worker"],
        "parameters": {"graceful": ActionParamSpec(type="boolean", required=False)},
        "max_targets": 2,
    }
    base.update(overrides)
    return ActionConfig.model_validate(base)


def permissive_guards() -> ActionGuards:
    return ActionGuards(
        kill_switch=KillSwitch(),
        rate_limiter=RateLimiter(
            RateLimitConfig(max_actions=100, window_seconds=10_000), lambda: 0.0
        ),
        circuit_breaker=CircuitBreaker(CircuitBreakerConfig(failure_threshold=100)),
    )


def make_surface(
    *,
    executor: ActionExecutor | None = None,
    gate: ApprovalGate | None = None,
    actions: list[ActionConfig] | None = None,
    guards: ActionGuards | None = None,
    audit: AuditLog | None = None,
) -> tuple[GatedActionSurface, AuditLog]:
    audit = audit or AuditLog(clock=lambda: FIXED)
    counter = itertools.count()
    surface = GatedActionSurface(
        allowlist=ActionAllowlist(actions or [restart_action()]),
        guards=guards or permissive_guards(),
        audit=audit,
        executor=executor or FakeActionExecutor(),
        gate=gate or ScriptedApprovalGate(True),
        id_factory=lambda: f"p{next(counter)}",
        clock=lambda: FIXED,
    )
    return surface, audit
