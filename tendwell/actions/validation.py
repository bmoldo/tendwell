"""Deterministic, pre-human validation of an action proposal.

Runs entirely without the LLM and before any human is bothered. A proposal that
fails here is rejected and logged; it never reaches the approval queue. This is
the deterministic checkpoint the model's output must pass before a human ever
sees it.
"""

from __future__ import annotations

from tendwell.actions.allowlist import ActionAllowlist, _reserved
from tendwell.actions.guards import ActionGuards
from tendwell.actions.types import ActionProposal, ValidationCode, ValidationOutcome


def validate_proposal(
    proposal: ActionProposal,
    allowlist: ActionAllowlist,
    guards: ActionGuards,
) -> ValidationOutcome:
    """Validate a proposal against the allowlist, scope, schema, and guards."""
    if guards.kill_switch.engaged:
        return ValidationOutcome(
            ValidationCode.KILL_SWITCH, "kill switch is engaged; no actions are accepted"
        )

    if _reserved(proposal.action):
        return ValidationOutcome(
            ValidationCode.RESERVED,
            f"action {proposal.action!r} references a reserved subsystem",
        )

    action = allowlist.get(proposal.action)
    if action is None:
        return ValidationOutcome(
            ValidationCode.UNKNOWN_ACTION,
            f"action {proposal.action!r} is not on the allowlist",
        )

    if not proposal.targets:
        return ValidationOutcome(
            ValidationCode.NO_TARGETS, "an action must name at least one target"
        )

    schema = allowlist.validate_arguments(action, dict(proposal.parameters))
    if not schema.ok:
        return schema

    out_of_scope = [t for t in proposal.targets if t not in action.scope]
    if out_of_scope:
        return ValidationOutcome(
            ValidationCode.OUT_OF_SCOPE,
            f"targets outside the action's scope: {', '.join(out_of_scope)}",
        )

    if action.max_targets is not None and len(proposal.targets) > action.max_targets:
        return ValidationOutcome(
            ValidationCode.TOO_MANY_TARGETS,
            f"{len(proposal.targets)} targets exceeds max_targets={action.max_targets}",
        )

    if guards.circuit_breaker.is_open:
        return ValidationOutcome(
            ValidationCode.BREAKER_OPEN,
            "circuit breaker is open after repeated failures; actions are paused",
        )

    if not guards.rate_limiter.allowed():
        return ValidationOutcome(
            ValidationCode.RATE_LIMITED, "action rate limit reached for the current window"
        )

    return ValidationOutcome(ValidationCode.OK)
