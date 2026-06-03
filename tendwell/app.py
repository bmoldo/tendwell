"""Application wiring: build the agent and its adapters from validated config.

This is the single place that turns a ``TendwellConfig`` into running
components. Concrete adapters (which pull in optional dependencies like openai,
httpx, chromadb) are imported lazily so that injecting fakes in tests does not
require those packages, and so an unused adapter never forces its dependency.

``llm`` and ``embeddings`` can be injected, which is how the end-to-end tests run
the real wiring (synthetic source, Chroma store, agent loop) with no network and
no model.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from tendwell.config.models import (
    HttpJsonSourceConfig,
    LokiSourceConfig,
    PrometheusSourceConfig,
    SyntheticSourceConfig,
    TendwellConfig,
)
from tendwell.context.embeddings import EmbeddingsClient
from tendwell.core.agent import HealthAnalyzer
from tendwell.core.types import HealthReport
from tendwell.interfaces.context_store import ContextStore
from tendwell.interfaces.data_source import DataSource
from tendwell.interfaces.llm import LLMBackend

if TYPE_CHECKING:
    from tendwell.actions.approval import ApprovalGate
    from tendwell.actions.executor import ActionExecutor
    from tendwell.actions.pipeline import GatedActionSurface
    from tendwell.actions.types import ActionResult


class ConfigError(Exception):
    """A configuration value is valid in shape but cannot be wired up."""


def resolve_secret(env_name: str | None) -> str | None:
    """Read a secret from the named environment variable, if any."""
    if not env_name:
        return None
    return os.environ.get(env_name)


def build_sources(config: TendwellConfig) -> tuple[dict[str, DataSource], dict[str, str]]:
    """Construct every configured data source and a query-id -> source map."""
    sources: dict[str, DataSource] = {}
    query_owners: dict[str, str] = {}
    for source_config in config.data_sources:
        raw = source_config.model_dump()
        if source_config.type == "prometheus":
            from tendwell.sources.prometheus import PrometheusDataSource

            prom = PrometheusSourceConfig.model_validate(raw)
            token = resolve_secret(prom.auth.token_env)
            sources[prom.name] = PrometheusDataSource(prom, token=token)
            query_ids = [q.id for q in prom.queries]
        elif source_config.type == "synthetic":
            from tendwell.demo.synthetic import SyntheticDataSource

            synthetic = SyntheticSourceConfig.model_validate(raw)
            sources[synthetic.name] = SyntheticDataSource(synthetic)
            query_ids = [q.id for q in synthetic.queries]
        elif source_config.type == "loki":
            from tendwell.sources.loki import LokiDataSource

            loki = LokiSourceConfig.model_validate(raw)
            sources[loki.name] = LokiDataSource(loki, token=resolve_secret(loki.auth.token_env))
            query_ids = [q.id for q in loki.queries]
        elif source_config.type == "http_json":
            from tendwell.sources.http_json import HttpJsonDataSource

            http_json = HttpJsonSourceConfig.model_validate(raw)
            sources[http_json.name] = HttpJsonDataSource(
                http_json, token=resolve_secret(http_json.auth.token_env)
            )
            query_ids = [q.id for q in http_json.queries]
        else:
            raise ConfigError(f"unknown data source type: {source_config.type!r}")

        for query_id in query_ids:
            query_owners[query_id] = source_config.name
    return sources, query_owners


def build_embeddings(config: TendwellConfig) -> EmbeddingsClient:
    """Construct the configured embeddings client (local-first by default)."""
    if config.embeddings.provider == "hash":
        from tendwell.context.embeddings import FakeEmbeddings

        return FakeEmbeddings()
    from tendwell.context.embeddings import OpenAICompatibleEmbeddings

    return OpenAICompatibleEmbeddings(
        config.embeddings, api_key=resolve_secret(config.embeddings.api_key_env)
    )


def build_context_store(config: TendwellConfig, embeddings: EmbeddingsClient) -> ContextStore:
    """Construct the configured vector store.

    Chroma is the persistent default; ``memory`` is the dependency-free store
    used by the instant demo and tests. ``pgvector`` and ``qdrant`` are reserved.
    """
    store_config = config.context.vector_store
    if store_config.type == "memory":
        from tendwell.context.memory_store import InMemoryContextStore

        return InMemoryContextStore(embeddings)
    if store_config.type == "chroma":
        from tendwell.context.chroma_store import ChromaContextStore

        # An empty path selects an in-memory Chroma store, which the tests use.
        return ChromaContextStore(embeddings, path=store_config.path or None)
    raise ConfigError(
        f"vector store '{store_config.type}' is not implemented yet; use 'chroma' or 'memory'"
    )


async def index_context(store: ContextStore, config: TendwellConfig) -> None:
    """Run every configured context loader and upsert its documents."""
    for loader_config in config.context.loaders:
        if loader_config.type != "markdown":
            raise ConfigError(f"context loader '{loader_config.type}' is not implemented yet")
        if not loader_config.path:
            raise ConfigError("markdown loader requires a 'path'")
        from tendwell.context.markdown_loader import MarkdownContextLoader

        extra = loader_config.model_dump()
        loader = MarkdownContextLoader(
            path=loader_config.path,
            chunk_size=int(extra.get("chunk_size", 800)),
            chunk_overlap=int(extra.get("chunk_overlap", 150)),
        )
        await store.upsert(await loader.load())


def build_llm(config: TendwellConfig) -> LLMBackend:
    """Construct the configured LLM backend (OpenAI-compatible, or the stub)."""
    if config.llm.provider == "stub":
        from tendwell.llm.stub import StubLLMBackend

        return StubLLMBackend()
    from tendwell.llm.openai_backend import OpenAICompatibleLLMBackend

    return OpenAICompatibleLLMBackend(config.llm, api_key=resolve_secret(config.llm.api_key_env))


def build_action_surface(
    config: TendwellConfig,
    *,
    executor: ActionExecutor,
    gate: ApprovalGate,
    audit_path: str | None = "./data/audit.jsonl",
) -> GatedActionSurface | None:
    """Construct the action surface, or ``None`` when actions are not enabled.

    Returns ``None`` for the default read-only posture: with no surface, the
    agent is structurally unable to mutate anything. Audit is always on; there is
    no path to disable it.
    """
    permissions = config.permissions
    if permissions.mode != "actions_enabled" or not permissions.actions:
        return None

    import time

    from tendwell.actions.allowlist import ActionAllowlist
    from tendwell.actions.audit import AuditLog
    from tendwell.actions.guards import (
        ActionGuards,
        CircuitBreaker,
        KillSwitch,
        RateLimiter,
    )
    from tendwell.actions.pipeline import GatedActionSurface

    safety = permissions.safety
    guards = ActionGuards(
        kill_switch=KillSwitch(safety.kill_switch_file),
        rate_limiter=RateLimiter(safety.rate_limit, time.monotonic),
        circuit_breaker=CircuitBreaker(safety.circuit_breaker),
    )
    return GatedActionSurface(
        allowlist=ActionAllowlist(permissions.actions),
        guards=guards,
        audit=AuditLog(path=audit_path),
        executor=executor,
        gate=gate,
    )


async def run_analysis(
    config: TendwellConfig,
    question: str | None = None,
    *,
    llm: LLMBackend | None = None,
    embeddings: EmbeddingsClient | None = None,
    action_surface: GatedActionSurface | None = None,
) -> HealthReport:
    """Build the full stack from config, index context, and run one analysis.

    When ``action_surface`` is provided, the model may propose actions through it;
    proposals are validated and collected but never executed here.
    """
    sources, query_owners = build_sources(config)
    store = build_context_store(config, embeddings or build_embeddings(config))
    await index_context(store, config)
    analyzer = HealthAnalyzer(
        sources=sources,
        query_owners=query_owners,
        slos=config.slos,
        context_store=store,
        llm=llm or build_llm(config),
        agent_config=config.agent,
        fallback_max_retries=config.llm.fallback_max_retries,
        action_surface=action_surface,
    )
    try:
        return await analyzer.analyze(question)
    finally:
        for source in sources.values():
            await source.close()
        await store.close()


async def run_on_demand(
    config: TendwellConfig,
    question: str | None = None,
    *,
    llm: LLMBackend | None = None,
    embeddings: EmbeddingsClient | None = None,
    executor: ActionExecutor | None = None,
    gate: ApprovalGate | None = None,
) -> tuple[HealthReport, list[ActionResult]]:
    """Run an analysis and then process any proposals through the human gate.

    Analysis and execution are separate phases: the model proposes during
    analysis, and only afterwards are validated proposals taken through human
    approval and (if approved) the executor. With actions disabled, the second
    phase is a no-op and no surface exists.
    """
    surface: GatedActionSurface | None = None
    if config.permissions.mode == "actions_enabled" and config.permissions.actions:
        from tendwell.actions.approval import CLIApprovalGate
        from tendwell.actions.executor import FakeActionExecutor

        surface = build_action_surface(
            config,
            executor=executor or FakeActionExecutor(),
            gate=gate or CLIApprovalGate(),
        )

    report = await run_analysis(
        config, question, llm=llm, embeddings=embeddings, action_surface=surface
    )
    results = await surface.process_pending() if surface is not None else []
    return report, results
