"""Append-only, tamper-evident audit log for the action lifecycle.

Every transition in an action's life is an event: proposal created, validation
result, approval or rejection (with human identity), execution start, each
per-target outcome, execution end. The log answers, without ambiguity, "what was
attempted" versus "what actually completed" - the exact question an incident
review or a regulator asks.

Tamper-evidence is a hash chain: each event carries the hash of the previous
one, so a removed or altered entry breaks the chain and is detectable. There is
no edit, no delete, and no config flag to silence it - consistent with the
locked audit guarantee from Phase 0. Callers must never place secrets in event
details; nothing here logs credentials.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

GENESIS_HASH = "0" * 64


class AuditEventType(StrEnum):
    """Every lifecycle transition that is recorded."""

    PROPOSAL_CREATED = "proposal_created"
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_REJECTED = "validation_rejected"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_TIMEOUT = "approval_timeout"
    EXECUTION_STARTED = "execution_started"
    TARGET_OUTCOME = "target_outcome"
    EXECUTION_COMPLETED = "execution_completed"
    DRY_RUN_PLANNED = "dry_run_planned"
    KILL_SWITCH_ENGAGED = "kill_switch_engaged"
    ACTION_BLOCKED = "action_blocked"


@dataclass(frozen=True)
class AuditEvent:
    """A single, immutable audit record linked to its predecessor by hash."""

    seq: int
    timestamp: str
    event_type: AuditEventType
    proposal_id: str
    details: Mapping[str, object]
    prev_hash: str
    hash: str

    def payload(self) -> dict[str, object]:
        """The hashed content, excluding the event's own hash."""
        return {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "event_type": str(self.event_type),
            "proposal_id": self.proposal_id,
            "details": dict(self.details),
            "prev_hash": self.prev_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.payload(), "hash": self.hash}


def _hash_payload(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_hash(
    seq: int,
    timestamp: str,
    event_type: AuditEventType,
    proposal_id: str,
    details: Mapping[str, object],
    prev_hash: str,
) -> str:
    """Compute the chain hash for an event's content."""
    return _hash_payload(
        {
            "seq": seq,
            "timestamp": timestamp,
            "event_type": str(event_type),
            "proposal_id": proposal_id,
            "details": dict(details),
            "prev_hash": prev_hash,
        }
    )


def verify_chain(events: Sequence[AuditEvent]) -> bool:
    """Return ``True`` only if every hash and link is intact and in order."""
    prev = GENESIS_HASH
    for index, event in enumerate(events):
        if event.seq != index:
            return False
        if event.prev_hash != prev:
            return False
        if event.hash != _hash_payload(event.payload()):
            return False
        prev = event.hash
    return True


class AuditLog:
    """An append-only hash-chained log. No edit, no delete, no disable."""

    def __init__(
        self,
        path: str | Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._events: list[AuditEvent] = []
        self._path = Path(path) if path else None
        self._clock = clock or (lambda: datetime.now(UTC))
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def events(self) -> Sequence[AuditEvent]:
        return tuple(self._events)

    def append(
        self,
        event_type: AuditEventType,
        proposal_id: str,
        details: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        """Record a new event, chained to the previous one."""
        seq = len(self._events)
        prev_hash = self._events[-1].hash if self._events else GENESIS_HASH
        timestamp = self._clock().isoformat()
        clean_details = dict(details or {})
        event = AuditEvent(
            seq=seq,
            timestamp=timestamp,
            event_type=event_type,
            proposal_id=proposal_id,
            details=clean_details,
            prev_hash=prev_hash,
            hash=compute_hash(seq, timestamp, event_type, proposal_id, clean_details, prev_hash),
        )
        self._events.append(event)
        if self._path is not None:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=True) + "\n")
        return event

    def verify(self) -> bool:
        """Whether the in-memory chain is intact."""
        return verify_chain(self._events)

    def events_for(self, proposal_id: str) -> list[AuditEvent]:
        """All events recorded for one proposal, in order."""
        return [e for e in self._events if e.proposal_id == proposal_id]
