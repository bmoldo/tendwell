"""The health-analysis agent loop.

Hybrid by design: a deterministic pre-fetch evaluates every SLO without any LLM,
so even a weak model that fails every tool call still gets a fully-populated
snapshot to explain. The LLM then adds interpretation and correlates breaches
with retrieved knowledge.

The agent is read-only unless an action surface is wired in. Even then, the model
can only PROPOSE actions through the surface's tool; proposals are validated and
collected during the run but never executed here. Executing a proposal is a
separate, human-gated step the agent has no path to.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from tendwell.config.models import SLO, AgentConfig
from tendwell.core.reasoning import NativeToolDriver, ReActDriver
from tendwell.core.tools import ToolExecutor
from tendwell.core.types import (
    Citation,
    HealthReport,
    HealthSnapshot,
    SLOState,
    SLOStatus,
)
from tendwell.interfaces.context_store import ContextStore, RetrievedChunk
from tendwell.interfaces.data_source import DataSource
from tendwell.interfaces.llm import LLMBackend

if TYPE_CHECKING:
    from tendwell.actions.pipeline import GatedActionSurface


def _evaluate(value: float, threshold: float, direction: str) -> SLOState:
    """Healthy when the value is on the configured side of the threshold."""
    if direction == "below":
        return SLOState.OK if value <= threshold else SLOState.BREACHED
    return SLOState.OK if value >= threshold else SLOState.BREACHED


def deterministic_summary(snapshot: HealthSnapshot) -> str:
    """A plain-language summary computed without any model.

    Used as the report summary when the LLM produced nothing usable (for
    example a truncated run), so output never depends on model quality for the
    basic facts.
    """
    if snapshot.breaches:
        parts = [
            f"{s.name} ({s.metric}={s.observed_value:g}, threshold {s.direction} {s.threshold:g})"
            for s in snapshot.breaches
        ]
        return f"{len(snapshot.breaches)} SLO(s) breached: " + "; ".join(parts)
    if snapshot.unknowns:
        return f"All evaluable SLOs are healthy; {len(snapshot.unknowns)} could not be evaluated."
    return "All SLOs are healthy."


def _render_snapshot(snapshot: HealthSnapshot) -> str:
    lines = ["Current SLO status (deterministically evaluated):"]
    for s in snapshot.statuses:
        observed = "n/a" if s.observed_value is None else f"{s.observed_value:g}"
        line = (
            f"- {s.name} [{s.state}]: {s.metric}={observed}, healthy {s.direction} {s.threshold:g}"
        )
        if s.detail:
            line += f" ({s.detail})"
        lines.append(line)
    return "\n".join(lines)


def _render_context(chunks: Sequence[RetrievedChunk]) -> str:
    if not chunks:
        return "No knowledge context was retrieved."
    lines = ["Relevant knowledge context (cite sources by their [source] tag):"]
    for chunk in chunks:
        lines.append(f"[{chunk.source}] {chunk.text}")
    return "\n".join(lines)


class HealthAnalyzer:
    """Assembles a snapshot, retrieves context, reasons, and reports."""

    def __init__(
        self,
        sources: Mapping[str, DataSource],
        query_owners: Mapping[str, str],
        slos: Sequence[SLO],
        context_store: ContextStore,
        llm: LLMBackend,
        agent_config: AgentConfig,
        fallback_max_retries: int = 2,
        action_surface: GatedActionSurface | None = None,
    ) -> None:
        self._sources = dict(sources)
        self._query_owners = dict(query_owners)
        self._slos = list(slos)
        self._store = context_store
        self._llm = llm
        self._agent = agent_config
        self._fallback_max_retries = fallback_max_retries
        self._action_surface = action_surface

    async def _build_snapshot(self) -> HealthSnapshot:
        statuses: list[SLOStatus] = []
        for slo in self._slos:
            owner = self._query_owners.get(slo.metric)
            source = self._sources.get(owner) if owner else None
            if source is None:
                statuses.append(
                    SLOStatus(
                        name=slo.name,
                        metric=slo.metric,
                        state=SLOState.UNKNOWN,
                        threshold=slo.threshold,
                        direction=slo.direction,
                        detail="no data source provides this metric",
                    )
                )
                continue
            try:
                result = await source.query(slo.metric)
            except KeyError:
                statuses.append(
                    SLOStatus(
                        name=slo.name,
                        metric=slo.metric,
                        state=SLOState.UNKNOWN,
                        threshold=slo.threshold,
                        direction=slo.direction,
                        detail="query not configured on its source",
                    )
                )
                continue
            except Exception as exc:
                statuses.append(
                    SLOStatus(
                        name=slo.name,
                        metric=slo.metric,
                        state=SLOState.UNKNOWN,
                        threshold=slo.threshold,
                        direction=slo.direction,
                        detail=f"source error: {exc}",
                    )
                )
                continue

            value = result.latest_value
            if value is None:
                statuses.append(
                    SLOStatus(
                        name=slo.name,
                        metric=slo.metric,
                        state=SLOState.UNKNOWN,
                        threshold=slo.threshold,
                        direction=slo.direction,
                        detail="no samples returned",
                    )
                )
                continue

            statuses.append(
                SLOStatus(
                    name=slo.name,
                    metric=slo.metric,
                    state=_evaluate(value, slo.threshold, slo.direction),
                    threshold=slo.threshold,
                    direction=slo.direction,
                    observed_value=value,
                    samples=result.samples,
                )
            )
        return HealthSnapshot(statuses=statuses, taken_at=datetime.now(UTC))

    def _retrieval_query(self, snapshot: HealthSnapshot, question: str | None) -> str:
        if question:
            return question
        if snapshot.breaches:
            metrics = " ".join(s.metric for s in snapshot.breaches)
            return f"{metrics} incident runbook mitigation"
        return ""

    def _build_user_prompt(
        self,
        snapshot: HealthSnapshot,
        chunks: Sequence[RetrievedChunk],
        question: str | None,
    ) -> str:
        task = question or "Assess current production health and explain any breaches."
        return (
            f"{_render_snapshot(snapshot)}\n\n"
            f"{_render_context(chunks)}\n\n"
            f"Task: {task}\n"
            "Explain the current health in plain language. When you reference a "
            "runbook or postmortem, cite it by the exact [source] tag shown above; "
            "do not invent sources. You may use the read-only tools to drill down."
        )

    async def analyze(self, question: str | None = None) -> HealthReport:
        """Run one health analysis and return a report.

        Any action proposals the model makes are validated and collected on the
        configured surface; they are returned in the report as pending and are
        not executed here.
        """
        snapshot = await self._build_snapshot()

        query = self._retrieval_query(snapshot, question)
        chunks = await self._store.retrieve(query, k=5) if query else []
        citations = tuple(
            Citation(
                document_id=c.document_id,
                source=c.source,
                text=c.text,
                score=c.score,
            )
            for c in chunks
        )

        executor = ToolExecutor(
            self._sources, self._store, snapshot, action_surface=self._action_surface
        )
        driver = (
            NativeToolDriver(self._llm)
            if self._llm.supports_native_tool_calling
            else ReActDriver(self._llm, max_retries=self._fallback_max_retries)
        )

        result = await driver.run(
            system_prompt=self._agent.persona,
            user_prompt=self._build_user_prompt(snapshot, chunks, question),
            executor=executor,
            max_steps=self._agent.max_reasoning_steps,
        )

        summary = result.answer.strip() or deterministic_summary(snapshot)
        proposals = tuple(self._action_surface.pending) if self._action_surface is not None else ()
        return HealthReport(
            overall=snapshot.overall_severity,
            summary=summary,
            snapshot=snapshot,
            citations=citations,
            truncated=result.truncated,
            truncation_note=result.note,
            proposals=proposals,
        )
