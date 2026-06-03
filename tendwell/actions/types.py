"""Types for the action surface.

These model the full lifecycle of a mutating action: a proposal (the only thing
the LLM can produce), the deterministic validation outcome, the human approval
decision, and the per-target execution result. Keeping per-target outcomes
first-class is deliberate: real actions are not atomic, and "2 of 3 succeeded"
must be representable without ambiguity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class TargetStatus(StrEnum):
    """Outcome for a single target of an action."""

    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    PLANNED = "planned"  # dry-run: what would happen, nothing mutated


class ValidationCode(StrEnum):
    """Result of deterministic, pre-human validation of a proposal."""

    OK = "ok"
    UNKNOWN_ACTION = "unknown_action"
    RESERVED = "reserved"
    NO_TARGETS = "no_targets"
    SCHEMA_INVALID = "schema_invalid"
    OUT_OF_SCOPE = "out_of_scope"
    TOO_MANY_TARGETS = "too_many_targets"
    RATE_LIMITED = "rate_limited"
    BREAKER_OPEN = "breaker_open"
    KILL_SWITCH = "kill_switch"


class ActionState(StrEnum):
    """Terminal state of a proposal as it moves through the pipeline."""

    REJECTED_VALIDATION = "rejected_validation"
    REJECTED_BY_HUMAN = "rejected_by_human"
    APPROVAL_TIMEOUT = "approval_timeout"
    KILLED = "killed"
    DRY_RUN = "dry_run"
    EXECUTED = "executed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class ActionProposal:
    """A proposed mutation. The only action-related thing the LLM can emit.

    Recording a proposal executes nothing. It carries the action name, the
    targets it would touch, typed arguments, the model's stated reason, and a
    dry-run flag. ``id`` is assigned by the surface, not the model.
    """

    id: str
    action: str
    targets: tuple[str, ...]
    parameters: Mapping[str, object]
    reason: str
    created_at: datetime
    dry_run: bool = False


@dataclass(frozen=True)
class ValidationOutcome:
    """The deterministic verdict on a proposal, before any human is involved."""

    code: ValidationCode
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.code is ValidationCode.OK


@dataclass(frozen=True)
class ApprovalDecision:
    """A human's decision on a validated proposal, with identity and time."""

    approved: bool
    approver: str
    decided_at: datetime
    reason: str = ""
    timed_out: bool = False


@dataclass(frozen=True)
class TargetOutcome:
    """The result of acting on one target."""

    target: str
    status: TargetStatus
    detail: str = ""


@dataclass(frozen=True)
class ActionResult:
    """The complete outcome of one proposal through the pipeline."""

    proposal_id: str
    action: str
    state: ActionState
    dry_run: bool
    target_outcomes: Sequence[TargetOutcome] = field(default_factory=tuple)
    approver: str | None = None
    detail: str = ""

    @property
    def executed(self) -> bool:
        """Whether anything was actually mutated (true for full or partial)."""
        return self.state in (ActionState.EXECUTED, ActionState.PARTIAL)
