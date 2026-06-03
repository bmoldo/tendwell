"""Result types produced by the agent loop.

The deterministic pre-fetch builds a ``HealthSnapshot`` (per-SLO status computed
without any LLM), the LLM adds interpretation, and the run ends in a
``HealthReport``. Keeping these types free of any backend specifics lets the
core loop stay independent of which data source, model, or store is wired in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from tendwell.interfaces.data_source import MetricSample
from tendwell.interfaces.output import Severity

if TYPE_CHECKING:
    from tendwell.actions.types import ActionProposal


class SLOState(StrEnum):
    """Evaluated state of a single SLO."""

    OK = "ok"
    BREACHED = "breached"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SLOStatus:
    """Deterministic evaluation of one SLO against observed signal.

    ``observed_value`` is ``None`` when the source could not be queried or
    returned no samples, in which case ``state`` is ``UNKNOWN``. ``detail``
    carries a short reason, used for ``UNKNOWN`` to explain why.
    """

    name: str
    metric: str
    state: SLOState
    threshold: float
    direction: str
    observed_value: float | None = None
    samples: Sequence[MetricSample] = field(default_factory=tuple)
    detail: str | None = None


@dataclass(frozen=True)
class HealthSnapshot:
    """The full set of SLO evaluations at a point in time."""

    statuses: Sequence[SLOStatus]
    taken_at: datetime

    @property
    def breaches(self) -> list[SLOStatus]:
        """SLOs currently in a breached state."""
        return [s for s in self.statuses if s.state is SLOState.BREACHED]

    @property
    def unknowns(self) -> list[SLOStatus]:
        """SLOs that could not be evaluated."""
        return [s for s in self.statuses if s.state is SLOState.UNKNOWN]

    @property
    def overall_severity(self) -> Severity:
        """Worst-case severity across all SLOs.

        Any breach is critical; otherwise an unevaluable SLO is a warning;
        otherwise healthy.
        """
        if self.breaches:
            return Severity.CRITICAL
        if self.unknowns:
            return Severity.WARNING
        return Severity.OK


@dataclass(frozen=True)
class Citation:
    """A knowledge chunk the report relied on.

    Citations are built from chunks actually retrieved and shown to the model,
    never from text the model produced, so a model cannot invent a source.
    """

    document_id: str
    source: str
    text: str
    score: float


@dataclass(frozen=True)
class HealthReport:
    """The agent's complete output for one analysis run."""

    overall: Severity
    summary: str
    snapshot: HealthSnapshot
    citations: Sequence[Citation] = field(default_factory=tuple)
    recommendations: Sequence[str] = field(default_factory=tuple)
    truncated: bool = False
    truncation_note: str | None = None
    # Validated proposals the model made this run, awaiting human approval. These
    # have NOT executed; processing them is a separate, human-gated step.
    proposals: Sequence[ActionProposal] = field(default_factory=tuple)
