"""Human approval gates. The model has no path to any of these.

A validated proposal enters a pending state and must be approved by a human,
with identity and time captured, before it can execute. Approval is offered two
ways: synchronously at a CLI prompt, or asynchronously via a pending queue a
human resolves out of band. Neither is exposed as a tool, so the model cannot
approve its own proposals - approval is structurally a human act on a surface the
model cannot reach. Rejection or timeout means no execution.
"""

from __future__ import annotations

import asyncio
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TextIO

from tendwell.actions.types import ActionProposal, ApprovalDecision


def _now() -> datetime:
    return datetime.now(UTC)


class ApprovalGate(ABC):
    """Abstract human approval surface."""

    @abstractmethod
    async def decide(self, proposal: ActionProposal) -> ApprovalDecision:
        """Obtain a human decision for a validated proposal.

        Implementations must default to deny: if no human responds (timeout,
        closed input), return a non-approved decision.
        """


class CLIApprovalGate(ApprovalGate):
    """Synchronous approval at an interactive prompt."""

    def __init__(
        self,
        approver: str = "operator",
        input_func: Callable[[str], str] | None = None,
        stream: TextIO | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._approver = approver
        self._input = input_func or input
        self._stream = stream if stream is not None else sys.stdout
        self._clock = clock or _now

    async def decide(self, proposal: ActionProposal) -> ApprovalDecision:
        self._stream.write(
            f"\nAction approval required\n"
            f"  action:  {proposal.action}\n"
            f"  targets: {', '.join(proposal.targets)}\n"
            f"  reason:  {proposal.reason}\n"
        )
        self._stream.flush()
        try:
            answer = self._input("Approve this action? [y/N]: ").strip().lower()
        except EOFError:
            answer = ""
        approved = answer in ("y", "yes")
        return ApprovalDecision(
            approved=approved,
            approver=self._approver,
            decided_at=self._clock(),
            reason="approved at CLI" if approved else "rejected at CLI",
        )


@dataclass
class _Pending:
    event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: ApprovalDecision | None = None


class PendingApprovalQueue(ApprovalGate):
    """Asynchronous approval via a queue a human resolves out of band.

    ``decide`` registers the proposal and waits (up to ``timeout_seconds``) for a
    human to call ``approve`` or ``reject`` with their identity. A timeout yields
    a non-approved, timed-out decision.
    """

    def __init__(
        self,
        timeout_seconds: float = 300.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._clock = clock or _now
        self._pending: dict[str, _Pending] = {}

    @property
    def pending_ids(self) -> list[str]:
        return list(self._pending)

    def approve(self, proposal_id: str, approver: str, reason: str = "") -> None:
        self._resolve(proposal_id, approved=True, approver=approver, reason=reason)

    def reject(self, proposal_id: str, approver: str, reason: str = "") -> None:
        self._resolve(proposal_id, approved=False, approver=approver, reason=reason)

    def _resolve(self, proposal_id: str, approved: bool, approver: str, reason: str) -> None:
        pending = self._pending.get(proposal_id)
        if pending is None or pending.decision is not None:
            return
        pending.decision = ApprovalDecision(
            approved=approved,
            approver=approver,
            decided_at=self._clock(),
            reason=reason,
        )
        pending.event.set()

    async def decide(self, proposal: ActionProposal) -> ApprovalDecision:
        pending = _Pending()
        self._pending[proposal.id] = pending
        try:
            await asyncio.wait_for(pending.event.wait(), timeout=self._timeout)
        except TimeoutError:
            return ApprovalDecision(
                approved=False,
                approver="",
                decided_at=self._clock(),
                reason="approval timed out",
                timed_out=True,
            )
        finally:
            self._pending.pop(proposal.id, None)
        assert pending.decision is not None
        return pending.decision
