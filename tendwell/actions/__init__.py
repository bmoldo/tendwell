"""The human-gated, audited action surface.

The single route by which Tendwell can change production. The LLM can only
propose; deterministic validation and a human approval gate sit between a
proposal and any execution. With no surface configured, the agent remains
structurally unable to mutate anything.
"""

from tendwell.actions.allowlist import ActionAllowlist
from tendwell.actions.approval import (
    ApprovalGate,
    CLIApprovalGate,
    PendingApprovalQueue,
)
from tendwell.actions.audit import AuditEvent, AuditEventType, AuditLog, verify_chain
from tendwell.actions.executor import ActionExecutor, FakeActionExecutor
from tendwell.actions.guards import (
    ActionGuards,
    CircuitBreaker,
    KillSwitch,
    RateLimiter,
)
from tendwell.actions.pipeline import GatedActionSurface
from tendwell.actions.types import (
    ActionProposal,
    ActionResult,
    ActionState,
    ApprovalDecision,
    TargetOutcome,
    TargetStatus,
    ValidationCode,
    ValidationOutcome,
)
from tendwell.actions.validation import validate_proposal

__all__ = [
    "ActionAllowlist",
    "ActionExecutor",
    "ActionGuards",
    "ActionProposal",
    "ActionResult",
    "ActionState",
    "ApprovalDecision",
    "ApprovalGate",
    "AuditEvent",
    "AuditEventType",
    "AuditLog",
    "CLIApprovalGate",
    "CircuitBreaker",
    "FakeActionExecutor",
    "GatedActionSurface",
    "KillSwitch",
    "PendingApprovalQueue",
    "RateLimiter",
    "TargetOutcome",
    "TargetStatus",
    "ValidationCode",
    "ValidationOutcome",
    "validate_proposal",
    "verify_chain",
]
