"""GatedActionSurface: the propose -> validate -> approve -> execute pipeline.

This implements the Phase 0 ``ActionSurface`` ABC and is the single route by
which anything mutates the monitored system. The separation is the product:

- ``propose`` records intent and runs deterministic validation. It is what the
  ``propose_action`` tool calls. It executes nothing.
- ``process`` takes an already-validated proposal, obtains human approval through
  the gate, and only then runs the executor.

There is no method the model can reach that approves or executes. Proposing and
executing are different methods, with deterministic validation and a human gate
between them, by construction.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from tendwell.actions.allowlist import ActionAllowlist
from tendwell.actions.approval import ApprovalGate
from tendwell.actions.audit import AuditEventType, AuditLog
from tendwell.actions.executor import ActionExecutor
from tendwell.actions.guards import ActionGuards
from tendwell.actions.types import (
    ActionProposal,
    ActionResult,
    ActionState,
    TargetOutcome,
    TargetStatus,
    ValidationOutcome,
)
from tendwell.actions.validation import validate_proposal
from tendwell.interfaces.llm import ToolSpec
from tendwell.interfaces.output import ActionOutcome, ActionRequest, ActionSurface


def _now() -> datetime:
    return datetime.now(UTC)


class GatedActionSurface(ActionSurface):
    """The only path to mutation: validate, gate on a human, then execute."""

    def __init__(
        self,
        allowlist: ActionAllowlist,
        guards: ActionGuards,
        audit: AuditLog,
        executor: ActionExecutor,
        gate: ApprovalGate,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._allowlist = allowlist
        self._guards = guards
        self._audit = audit
        self._executor = executor
        self._gate = gate
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._clock = clock or _now
        self._pending: list[ActionProposal] = []

    @property
    def pending(self) -> Sequence[ActionProposal]:
        return tuple(self._pending)

    def propose_tool_spec(self) -> ToolSpec:
        """The ``propose_action`` tool schema, generated from the allowlist."""
        return self._allowlist.propose_tool_spec()

    # -- propose (tool-facing; executes nothing) ----------------------------
    def propose(
        self,
        action: str,
        targets: Sequence[str],
        parameters: Mapping[str, object],
        reason: str,
        dry_run: bool = False,
    ) -> tuple[ActionProposal | None, ValidationOutcome]:
        """Record a proposal and validate it deterministically. No execution.

        On success the proposal is queued as pending for human approval and
        returned. On failure ``None`` is returned with the rejection outcome.
        Both paths are audited.
        """
        proposal = ActionProposal(
            id=self._id_factory(),
            action=action,
            targets=tuple(targets),
            parameters=dict(parameters),
            reason=reason,
            created_at=self._clock(),
            dry_run=dry_run,
        )
        self._audit.append(
            AuditEventType.PROPOSAL_CREATED,
            proposal.id,
            {
                "action": action,
                "targets": list(proposal.targets),
                "reason": reason,
                "dry_run": dry_run,
            },
        )
        outcome = validate_proposal(proposal, self._allowlist, self._guards)
        if outcome.ok:
            self._audit.append(AuditEventType.VALIDATION_PASSED, proposal.id, {})
            self._pending.append(proposal)
            return proposal, outcome
        self._audit.append(
            AuditEventType.VALIDATION_REJECTED,
            proposal.id,
            {"code": str(outcome.code), "message": outcome.message},
        )
        return None, outcome

    # -- process (post-human; the only path that executes) ------------------
    async def process(self, proposal: ActionProposal) -> ActionResult:
        """Approve (human) and, only if approved, execute a validated proposal."""
        if self._guards.kill_switch.engaged:
            return self._blocked(proposal, "kill switch engaged before approval")

        if proposal.dry_run:
            return await self._dry_run(proposal)

        decision = await self._gate.decide(proposal)
        if decision.timed_out:
            self._audit.append(
                AuditEventType.APPROVAL_TIMEOUT, proposal.id, {"reason": decision.reason}
            )
            return ActionResult(
                proposal_id=proposal.id,
                action=proposal.action,
                state=ActionState.APPROVAL_TIMEOUT,
                dry_run=False,
                detail="approval timed out; not executed",
            )
        if not decision.approved:
            self._audit.append(
                AuditEventType.APPROVAL_REJECTED,
                proposal.id,
                {"approver": decision.approver, "reason": decision.reason},
            )
            return ActionResult(
                proposal_id=proposal.id,
                action=proposal.action,
                state=ActionState.REJECTED_BY_HUMAN,
                dry_run=False,
                approver=decision.approver,
                detail="rejected by human; not executed",
            )

        self._audit.append(
            AuditEventType.APPROVAL_GRANTED,
            proposal.id,
            {"approver": decision.approver, "decided_at": decision.decided_at.isoformat()},
        )

        # The kill switch halts pending executions too, even post-approval.
        if self._guards.kill_switch.engaged:
            return self._blocked(proposal, "kill switch engaged after approval")

        return await self._execute(proposal, decision.approver)

    async def process_pending(self) -> list[ActionResult]:
        """Process every queued proposal, clearing the queue."""
        proposals = list(self._pending)
        self._pending.clear()
        return [await self.process(p) for p in proposals]

    # -- internals ----------------------------------------------------------
    def _blocked(self, proposal: ActionProposal, reason: str) -> ActionResult:
        self._audit.append(AuditEventType.KILL_SWITCH_ENGAGED, proposal.id, {"reason": reason})
        self._audit.append(AuditEventType.ACTION_BLOCKED, proposal.id, {"reason": reason})
        return ActionResult(
            proposal_id=proposal.id,
            action=proposal.action,
            state=ActionState.KILLED,
            dry_run=proposal.dry_run,
            detail=reason,
        )

    async def _dry_run(self, proposal: ActionProposal) -> ActionResult:
        outcomes = [
            await self._executor.execute_target(proposal, target, dry_run=True)
            for target in proposal.targets
        ]
        self._audit.append(
            AuditEventType.DRY_RUN_PLANNED,
            proposal.id,
            {"targets": list(proposal.targets)},
        )
        return ActionResult(
            proposal_id=proposal.id,
            action=proposal.action,
            state=ActionState.DRY_RUN,
            dry_run=True,
            target_outcomes=tuple(outcomes),
            detail="dry run; nothing was mutated",
        )

    async def _execute_one(self, proposal: ActionProposal, target: str) -> TargetOutcome:
        action = self._allowlist.get(proposal.action)
        attempts = 2 if (action is not None and action.idempotent) else 1
        last: TargetOutcome | None = None
        for _ in range(attempts):
            try:
                last = await self._executor.execute_target(proposal, target, dry_run=False)
            except Exception as exc:
                last = TargetOutcome(target=target, status=TargetStatus.FAILURE, detail=str(exc))
            if last.status is TargetStatus.SUCCESS:
                break
        assert last is not None
        return last

    async def _execute(self, proposal: ActionProposal, approver: str) -> ActionResult:
        self._guards.rate_limiter.record()
        self._audit.append(
            AuditEventType.EXECUTION_STARTED,
            proposal.id,
            {"targets": list(proposal.targets), "approver": approver},
        )
        outcomes: list[TargetOutcome] = []
        for target in proposal.targets:
            outcome = await self._execute_one(proposal, target)
            outcomes.append(outcome)
            self._audit.append(
                AuditEventType.TARGET_OUTCOME,
                proposal.id,
                {"target": target, "status": str(outcome.status), "detail": outcome.detail},
            )

        succeeded = [o.target for o in outcomes if o.status is TargetStatus.SUCCESS]
        failed = [o.target for o in outcomes if o.status is TargetStatus.FAILURE]
        if failed and succeeded:
            state = ActionState.PARTIAL
        elif failed:
            state = ActionState.FAILED
        else:
            state = ActionState.EXECUTED

        if state is ActionState.EXECUTED:
            self._guards.circuit_breaker.record_success()
        else:
            self._guards.circuit_breaker.record_failure()

        self._audit.append(
            AuditEventType.EXECUTION_COMPLETED,
            proposal.id,
            {
                "state": str(state),
                "attempted": list(proposal.targets),
                "succeeded": succeeded,
                "failed": failed,
            },
        )
        return ActionResult(
            proposal_id=proposal.id,
            action=proposal.action,
            state=state,
            dry_run=False,
            target_outcomes=tuple(outcomes),
            approver=approver,
            detail=f"{len(succeeded)}/{len(outcomes)} targets succeeded",
        )

    # -- Phase 0 ActionSurface ABC -----------------------------------------
    async def approve(self, request: ActionRequest) -> bool:
        """Thin human-approval primitive for the abstract interface."""
        proposal = ActionProposal(
            id=self._id_factory(),
            action=request.name,
            targets=tuple(_targets_of(request.parameters)),
            parameters=dict(request.parameters),
            reason=request.reason,
            created_at=self._clock(),
        )
        decision = await self._gate.decide(proposal)
        return decision.approved

    async def execute(self, request: ActionRequest) -> ActionOutcome:
        """Run the full pipeline for a fresh request (validate, gate, execute)."""
        proposal, outcome = self.propose(
            action=request.name,
            targets=_targets_of(request.parameters),
            parameters=request.parameters,
            reason=request.reason,
        )
        if proposal is None:
            return ActionOutcome(
                name=request.name, approved=False, executed=False, detail=outcome.message
            )
        result = await self.process(proposal)
        approved = result.state not in (
            ActionState.REJECTED_BY_HUMAN,
            ActionState.APPROVAL_TIMEOUT,
            ActionState.KILLED,
        )
        return ActionOutcome(
            name=request.name,
            approved=approved,
            executed=result.executed,
            detail=str(result.state),
        )


def _targets_of(parameters: Mapping[str, object]) -> list[str]:
    raw = parameters.get("targets")
    if isinstance(raw, list):
        return [str(t) for t in raw]
    return []
