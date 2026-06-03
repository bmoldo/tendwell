"""Read-only tools exposed to the agent, with one schema shared by both paths.

The same ``ToolSpec`` set and the same ``ToolExecutor`` drive native tool
calling and the ReAct fallback, so the two paths can only differ in how the
model is prompted, never in what it can do. Every tool is read-only; no tool can
mutate anything. Invalid tool input becomes a structured error observation, not
an exception that aborts the run.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationError

from tendwell.interfaces.context_store import ContextStore, RetrievedChunk
from tendwell.interfaces.data_source import DataSource, QueryResult
from tendwell.interfaces.llm import ToolSpec

if TYPE_CHECKING:
    from tendwell.actions.pipeline import GatedActionSurface
    from tendwell.core.types import HealthSnapshot


class ProposeActionInput(BaseModel):
    """Arguments for the ``propose_action`` tool.

    Recording a proposal executes nothing; the agent cannot approve or run it.
    """

    model_config = ConfigDict(extra="forbid")

    action: str
    targets: list[str] = []
    parameters: dict[str, object] = {}
    reason: str
    dry_run: bool = False


class _ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryMetricsInput(_ToolInput):
    """Arguments for ``query_metrics``."""

    source: str
    query_id: str


class SearchKnowledgeInput(_ToolInput):
    """Arguments for ``search_knowledge``."""

    query: str
    k: int = 5


class GetHealthSnapshotInput(_ToolInput):
    """``get_health_snapshot`` takes no arguments."""


_INPUT_MODELS: dict[str, type[_ToolInput]] = {
    "query_metrics": QueryMetricsInput,
    "search_knowledge": SearchKnowledgeInput,
    "get_health_snapshot": GetHealthSnapshotInput,
}

_DESCRIPTIONS: dict[str, str] = {
    "query_metrics": (
        "Run a configured query against a named data source and return its "
        "normalized result (read-only)."
    ),
    "search_knowledge": (
        "Search the knowledge base (runbooks, postmortems, topology) and return "
        "the most relevant chunks with their sources (read-only)."
    ),
    "get_health_snapshot": (
        "Return the already-computed per-SLO health snapshot for this run (read-only)."
    ),
}


def tool_specs() -> list[ToolSpec]:
    """Build the tool schemas from the typed input models."""
    specs: list[ToolSpec] = []
    for name, model in _INPUT_MODELS.items():
        specs.append(
            ToolSpec(
                name=name,
                description=_DESCRIPTIONS[name],
                parameters=model.model_json_schema(),
            )
        )
    return specs


def query_result_to_dict(result: QueryResult) -> dict[str, object]:
    """Serialize a ``QueryResult`` into a compact JSON-friendly dict."""
    return {
        "query_id": result.query_id,
        "source": result.source,
        "kind": str(result.kind),
        "retrieved_at": result.retrieved_at.isoformat(),
        "latest_value": result.latest_value,
        "samples": [
            {
                "timestamp": s.timestamp.isoformat(),
                "value": s.value,
                "labels": dict(s.labels),
            }
            for s in result.samples
        ],
        "logs": [{"timestamp": e.timestamp.isoformat(), "message": e.message} for e in result.logs],
        "metadata": dict(result.metadata),
    }


def chunk_to_dict(chunk: RetrievedChunk) -> dict[str, object]:
    """Serialize a ``RetrievedChunk`` for a tool observation."""
    return {
        "document_id": chunk.document_id,
        "source": chunk.source,
        "score": chunk.score,
        "text": chunk.text,
    }


def snapshot_to_dict(snapshot: HealthSnapshot) -> dict[str, object]:
    """Serialize a ``HealthSnapshot`` for a tool observation."""
    return {
        "taken_at": snapshot.taken_at.isoformat(),
        "overall": str(snapshot.overall_severity),
        "statuses": [
            {
                "name": s.name,
                "metric": s.metric,
                "state": str(s.state),
                "observed_value": s.observed_value,
                "threshold": s.threshold,
                "direction": s.direction,
                "detail": s.detail,
            }
            for s in snapshot.statuses
        ],
    }


class ToolExecutor:
    """Validates and runs read-only tool calls against the wired components.

    ``snapshot`` is set by the agent loop after the deterministic pre-fetch so
    ``get_health_snapshot`` can re-read it without recomputation.
    """

    def __init__(
        self,
        sources: Mapping[str, DataSource],
        context_store: ContextStore,
        snapshot: HealthSnapshot,
        action_surface: GatedActionSurface | None = None,
    ) -> None:
        self._sources = dict(sources)
        self._store = context_store
        self.snapshot = snapshot
        self._action_surface = action_surface

    def tool_specs(self) -> list[ToolSpec]:
        """Tool schemas to advertise to the model.

        ``propose_action`` appears only when an action surface is configured;
        with none, the model has no action-related tool at all.
        """
        specs = tool_specs()
        if self._action_surface is not None:
            specs.append(self._action_surface.propose_tool_spec())
        return specs

    async def execute(self, name: str, arguments: Mapping[str, object]) -> dict[str, object]:
        """Run a tool call, always returning a structured observation.

        Returns ``{"ok": True, "result": ...}`` on success or
        ``{"ok": False, "error": ...}`` on any validation or execution problem.
        Never raises for bad model input.
        """
        if name == "propose_action" and self._action_surface is not None:
            return self._propose_action(arguments)

        model = _INPUT_MODELS.get(name)
        if model is None:
            return {
                "ok": False,
                "error": f"unknown tool '{name}'; valid tools: " + ", ".join(_INPUT_MODELS),
            }
        try:
            args = model.model_validate(dict(arguments))
        except ValidationError as exc:
            return {
                "ok": False,
                "error": f"invalid arguments for '{name}': {exc.errors(include_url=False)}",
            }

        try:
            if isinstance(args, QueryMetricsInput):
                return await self._query_metrics(args)
            if isinstance(args, SearchKnowledgeInput):
                return await self._search_knowledge(args)
            if isinstance(args, GetHealthSnapshotInput):
                return {"ok": True, "result": snapshot_to_dict(self.snapshot)}
        except Exception as exc:
            return {"ok": False, "error": f"tool '{name}' failed: {exc}"}
        return {"ok": False, "error": f"unhandled tool '{name}'"}

    async def _query_metrics(self, args: QueryMetricsInput) -> dict[str, object]:
        source = self._sources.get(args.source)
        if source is None:
            return {
                "ok": False,
                "error": f"unknown source '{args.source}'; valid sources: "
                + ", ".join(self._sources),
            }
        try:
            result = await source.query(args.query_id)
        except KeyError:
            return {
                "ok": False,
                "error": f"unknown query_id '{args.query_id}' on source '{args.source}'",
            }
        return {"ok": True, "result": query_result_to_dict(result)}

    async def _search_knowledge(self, args: SearchKnowledgeInput) -> dict[str, object]:
        chunks = await self._store.retrieve(args.query, k=args.k)
        return {"ok": True, "result": [chunk_to_dict(c) for c in chunks]}

    def _propose_action(self, arguments: Mapping[str, object]) -> dict[str, object]:
        """Record an action proposal for human approval. Executes nothing.

        The observation makes explicit that the proposal is only recorded and
        that the model can neither approve nor run it.
        """
        assert self._action_surface is not None
        try:
            args = ProposeActionInput.model_validate(dict(arguments))
        except ValidationError as exc:
            return {
                "ok": False,
                "error": f"invalid propose_action arguments: {exc.errors(include_url=False)}",
            }
        proposal, outcome = self._action_surface.propose(
            action=args.action,
            targets=args.targets,
            parameters=args.parameters,
            reason=args.reason,
            dry_run=args.dry_run,
        )
        if proposal is None:
            return {
                "ok": False,
                "error": f"proposal rejected by validation: {outcome.code} - {outcome.message}",
            }
        return {
            "ok": True,
            "result": {
                "proposal_id": proposal.id,
                "status": "recorded; pending human approval",
                "note": (
                    "This is recorded only. You cannot approve or execute it; a "
                    "human must approve before anything happens."
                ),
            },
        }


def observation_json(observation: Mapping[str, object]) -> str:
    """Render a tool observation as compact JSON for the transcript."""
    return json.dumps(observation, ensure_ascii=True, default=str)
