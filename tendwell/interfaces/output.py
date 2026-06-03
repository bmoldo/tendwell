"""OutputSink and ActionSurface interfaces, plus their data types.

These two interfaces are deliberately separate because they carry different
risk. An ``OutputSink`` only serves findings (to a daemon feed, an on-demand
response, an MCP tool result, a CLI, or a notification target); serving is
always safe. An ``ActionSurface`` is the only path by which the agent can ever
mutate the monitored system, and it is gated.

The security posture is enforced here:

- Read-only is the default. If no ``ActionSurface`` is configured, the agent
  cannot act, period.
- Every action is opt-in per action, scoped, and human-approval-gated by
  default. Approval is a real gate (``approve``), not a log line.
- Auditing of actions is always on and cannot be disabled. The audit record is
  written by the action pipeline, not by config choice.

Concrete sinks (FastAPI server, MCP server, CLI, notifiers) live under
``tendwell.output``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Severity(StrEnum):
    """Severity of a finding, ordered from healthy to most urgent."""

    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Finding:
    """A single health finding produced by the agent.

    ``evidence`` carries the supporting signal and retrieved context so a
    reader can audit the conclusion. ``slo`` names the SLO this finding relates
    to, when applicable.
    """

    id: str
    title: str
    summary: str
    severity: Severity
    created_at: datetime
    slo: str | None = None
    evidence: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionRequest:
    """A request to perform a gated, mutating action.

    ``name`` must match an action explicitly enabled in config; ``parameters``
    are the scoped arguments; ``reason`` is the agent's justification, recorded
    in the audit log.
    """

    name: str
    parameters: Mapping[str, object]
    reason: str


@dataclass(frozen=True)
class ActionOutcome:
    """The result of routing an ``ActionRequest`` through the gate."""

    name: str
    approved: bool
    executed: bool
    detail: str


class OutputSink(ABC):
    """Abstract surface that serves findings. Always read-only and safe."""

    @abstractmethod
    async def emit(self, findings: Sequence[Finding]) -> None:
        """Serve or deliver the given findings."""

    async def close(self) -> None:
        """Release any held resources. Default: no-op."""
        return None


class ActionSurface(ABC):
    """Abstract gated surface for mutating actions.

    This interface exists only when an operator has explicitly enabled actions.
    Implementations must enforce, in order: the action is enabled and in scope;
    approval (when required) is obtained via ``approve``; the attempt and its
    outcome are written to the audit log unconditionally; only then is the
    action executed.
    """

    @abstractmethod
    async def approve(self, request: ActionRequest) -> bool:
        """Obtain human approval for ``request``. Returns ``True`` if approved.

        Default-deny: an implementation that cannot reach an approver must
        return ``False``.
        """

    @abstractmethod
    async def execute(self, request: ActionRequest) -> ActionOutcome:
        """Validate, gate, audit, and (only if permitted) perform ``request``.

        Must write an audit record for every attempt regardless of outcome.
        Auditing cannot be disabled.
        """
