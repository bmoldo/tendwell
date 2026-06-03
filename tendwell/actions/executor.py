"""The deterministic, non-LLM executor.

Only an approved proposal reaches an executor, and the executor is the single
place that touches the monitored system. It acts per target and reports a
per-target outcome, so partial failure is a first-class result rather than an
edge case. A dry run plans without mutating.

Real executors acquire write-scoped credentials only for the execution at hand
and never hold them ambiently; the read path has no access to them. The bundled
``FakeActionExecutor`` performs no real work and is what CI and the demo use.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from tendwell.actions.types import ActionProposal, TargetOutcome, TargetStatus


class ActionExecutor(ABC):
    """Abstract per-target executor for approved actions."""

    @abstractmethod
    async def execute_target(
        self, proposal: ActionProposal, target: str, *, dry_run: bool
    ) -> TargetOutcome:
        """Act on a single target and return its outcome.

        Must not raise for an ordinary failure; return a ``FAILURE`` outcome
        instead. When ``dry_run`` is true it must mutate nothing and return a
        ``PLANNED`` outcome.
        """


class FakeActionExecutor(ActionExecutor):
    """A scriptable executor for tests and the demo. Performs no real work.

    Configure outcomes per target via ``statuses``; targets in ``raises`` raise,
    exercising the pipeline's exception handling. Records each executed target.
    """

    def __init__(
        self,
        default_status: TargetStatus = TargetStatus.SUCCESS,
        statuses: Mapping[str, TargetStatus] | None = None,
        raises: set[str] | None = None,
    ) -> None:
        self._default = default_status
        self._statuses = dict(statuses or {})
        self._raises = set(raises or set())
        #: (target, dry_run) for every call, for test assertions.
        self.calls: list[tuple[str, bool]] = []

    async def execute_target(
        self, proposal: ActionProposal, target: str, *, dry_run: bool
    ) -> TargetOutcome:
        self.calls.append((target, dry_run))
        if dry_run:
            return TargetOutcome(
                target=target,
                status=TargetStatus.PLANNED,
                detail=f"would run {proposal.action} on {target}",
            )
        if target in self._raises:
            raise RuntimeError(f"simulated failure acting on {target}")
        status = self._statuses.get(target, self._default)
        return TargetOutcome(target=target, status=status, detail=f"{proposal.action} {status}")
