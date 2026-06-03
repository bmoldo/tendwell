"""Typed, validated configuration models.

A single deployment is defined entirely by this config tree plus injected
secrets. The models enforce the locked-by-design defaults from the spec:

- ``permissions.mode`` defaults to ``read_only``.
- Audit logging cannot be disabled: setting ``audit.enabled: false`` is a
  validation error, not an accepted option.
- Defaults are local-first; see ``TendwellConfig.egress_targets`` for how
  off-host endpoints are detected so startup can warn about them.

Secrets are never values here. Where a credential is needed, config names the
environment variable that holds it (``*_env`` fields), never the secret itself.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Hosts that are considered on-host / local. An endpoint whose host is not in
# this set is treated as off-host egress for the startup warning.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", ""})


class _Strict(BaseModel):
    """Base for fully-typed config blocks. Unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")


class _Open(BaseModel):
    """Base for adapter blocks that carry backend-specific extra keys."""

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# LLM and embeddings
# ---------------------------------------------------------------------------
def _default_llm_params() -> dict[str, object]:
    """Default generation parameters: low temperature for stable analysis."""
    return {"temperature": 0.1}


class Capabilities(_Strict):
    """Declared capabilities of an LLM backend."""

    native_tool_calling: bool = True


class LLMConfig(_Strict):
    """OpenAI-compatible chat backend configuration.

    ``provider`` selects the backend: ``openai`` (the default, any
    OpenAI-compatible endpoint) or ``stub`` (a no-network demo backend used by
    the instant demo tier; produces a real report with deterministic facts and a
    fixed narrative).
    """

    provider: Literal["openai", "stub"] = "openai"
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen2.5:14b"
    api_key_env: str | None = None
    context_window: int = 32768
    params: dict[str, object] = Field(default_factory=_default_llm_params)
    capabilities: Capabilities = Field(default_factory=Capabilities)
    # ReAct fallback only: how many times to re-prompt a single step when the
    # model emits a malformed action/answer before degrading gracefully.
    fallback_max_retries: int = 2


class EmbeddingsConfig(_Strict):
    """OpenAI-compatible embeddings backend configuration.

    ``provider`` selects the backend: ``openai`` (the default, any
    OpenAI-compatible embeddings endpoint) or ``hash`` (a deterministic,
    no-network embedder used by the instant demo tier and tests).
    """

    provider: Literal["openai", "hash"] = "openai"
    base_url: str = "http://localhost:11434/v1"
    model: str = "nomic-embed-text"
    api_key_env: str | None = None


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------
class AuthConfig(_Strict):
    """Auth for a data source. The token, when used, is read from an env var."""

    mode: Literal["none", "bearer", "basic"] = "none"
    token_env: str | None = None


class DataSourceConfig(_Open):
    """Common data-source fields. Adapter-specific keys are preserved.

    ``type`` selects the adapter; each adapter re-validates this block against
    its own typed schema (for example ``PrometheusSourceConfig``). Documenting
    that schema is part of writing an adapter.
    """

    name: str
    type: str
    endpoint: str | None = None
    auth: AuthConfig = Field(default_factory=AuthConfig)


class PrometheusQuery(_Strict):
    """A named PromQL query."""

    id: str
    promql: str


class PrometheusSourceConfig(DataSourceConfig):
    """Config shape of the Prometheus adapter (first concrete data source).

    The adapter parses a ``DataSourceConfig`` of ``type: prometheus`` into this
    typed shape. Queries are operator-defined and never baked into the code.
    """

    type: Literal["prometheus"] = "prometheus"
    queries: list[PrometheusQuery] = Field(default_factory=list)


class SyntheticQuery(_Strict):
    """A named synthetic metric the demo source can generate."""

    id: str


class SyntheticSourceConfig(DataSourceConfig):
    """Config shape of the synthetic demo data source.

    ``scenario`` selects whether generated signal keeps every SLO healthy or
    breaches one, so the agent has something real to find. ``seed`` makes
    generation deterministic for stable CI assertions.
    """

    type: Literal["synthetic"] = "synthetic"
    scenario: Literal["healthy", "degraded"] = "healthy"
    seed: int = 0
    queries: list[SyntheticQuery] = Field(default_factory=list)


class LokiQuery(_Strict):
    """A named LogQL range query."""

    id: str
    logql: str
    limit: int = 100
    range_seconds: int = 300


class LokiSourceConfig(DataSourceConfig):
    """Config shape of the Loki logs adapter."""

    type: Literal["loki"] = "loki"
    queries: list[LokiQuery] = Field(default_factory=list)


class HttpJsonQuery(_Strict):
    """A named query against a JSON HTTP endpoint.

    ``path`` is appended to the source endpoint; ``value_path`` is a
    dot-separated path into the JSON response that points at a numeric value
    (list indices are written as integers, for example ``data.0.value``).
    """

    id: str
    path: str = ""
    value_path: str


class HttpJsonSourceConfig(DataSourceConfig):
    """Config shape of the generic HTTP/JSON metrics adapter."""

    type: Literal["http_json"] = "http_json"
    queries: list[HttpJsonQuery] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# SLOs
# ---------------------------------------------------------------------------
class SLO(_Strict):
    """A service-level objective expressed against a named query result.

    ``direction`` names the side of ``threshold`` that is considered healthy:
    ``below`` means healthy while the metric is under the threshold.
    """

    name: str
    metric: str
    threshold: float
    direction: Literal["above", "below"] = "below"


# ---------------------------------------------------------------------------
# Knowledge context
# ---------------------------------------------------------------------------
class VectorStoreConfig(_Open):
    """Vector store backend. Chroma is the local-first default.

    ``memory`` is a dependency-free in-process store used by the instant demo
    tier and tests; ``pgvector`` and ``qdrant`` are reserved for future adapters.
    """

    type: Literal["chroma", "memory", "pgvector", "qdrant"] = "chroma"
    path: str = "./data/vectors"


class LoaderConfig(_Open):
    """A knowledge context loader. Markdown directory is the default."""

    type: str = "markdown"
    path: str | None = None
    refresh: int = 3600


class ContextConfig(_Strict):
    """Knowledge context configuration."""

    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    loaders: list[LoaderConfig] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Permissions and security
# ---------------------------------------------------------------------------
# Substrings that may not appear in an action name. Tendwell's own config, the
# action allowlist, the audit log, the approval mechanism, and credentials are
# structurally untargetable: you cannot even declare an action that names them.
RESERVED_ACTION_SUBSTRINGS = frozenset(
    {"config", "allowlist", "audit", "approval", "approve", "credential", "secret"}
)


class ActionParamSpec(_Strict):
    """Typed schema for one declared action argument."""

    type: Literal["string", "integer", "number", "boolean"] = "string"
    required: bool = True


class ActionConfig(_Strict):
    """An opt-in, scoped, human-gated action capability.

    Actions do not exist unless declared here. Each has a stable name, a typed
    argument schema, and a scope (the set of targets it may touch). Approval is
    mandatory and cannot be turned off: auto-approval is deliberately not
    available in the open core.
    """

    name: str
    require_approval: bool = True
    scope: list[str] = Field(default_factory=list)
    parameters: dict[str, ActionParamSpec] = Field(default_factory=dict)
    idempotent: bool = False
    max_targets: int | None = None

    @field_validator("name")
    @classmethod
    def _name_not_reserved(cls, value: str) -> str:
        lowered = value.lower()
        for token in RESERVED_ACTION_SUBSTRINGS:
            if token in lowered:
                raise ValueError(
                    f"action name {value!r} references the reserved subsystem "
                    f"{token!r}; Tendwell's config, allowlist, audit log, approval "
                    "mechanism, and credentials are structurally untargetable"
                )
        return value

    @field_validator("require_approval")
    @classmethod
    def _approval_is_mandatory(cls, value: bool) -> bool:
        if value is False:
            raise ValueError(
                "actions are human-approval-gated; 'require_approval: false' "
                "(auto-approval) is not available in the open core"
            )
        return value


class RateLimitConfig(_Strict):
    """Cap on executed actions within a sliding window."""

    max_actions: int = 5
    window_seconds: float = 60.0


class CircuitBreakerConfig(_Strict):
    """Trip after repeated execution failures to stop a flapping loop."""

    failure_threshold: int = 3


class ActionSafetyConfig(_Strict):
    """Containment controls for the action surface."""

    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    # When set, the presence of this file engages the kill switch: all pending
    # and future executions halt immediately, independent of config reload.
    kill_switch_file: str | None = None


class AuditConfig(_Strict):
    """Audit logging configuration.

    Audit logging for actions is always on and cannot be disabled. The
    ``enabled`` field exists for documentation and forward compatibility only;
    setting it to ``false`` is rejected, by design.
    """

    enabled: bool = True

    @field_validator("enabled")
    @classmethod
    def _audit_cannot_be_disabled(cls, value: bool) -> bool:
        if value is False:
            raise ValueError(
                "audit logging cannot be disabled; remove 'audit.enabled: false' "
                "from the config (audit logging for actions is always on by design)"
            )
        return value


class PermissionsConfig(_Strict):
    """Read-only by default. Actions are opt-in and gated."""

    mode: Literal["read_only", "actions_enabled"] = "read_only"
    actions: list[ActionConfig] = Field(default_factory=list)
    safety: ActionSafetyConfig = Field(default_factory=ActionSafetyConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)


# ---------------------------------------------------------------------------
# Output / serving
# ---------------------------------------------------------------------------
class ServerAuthConfig(_Strict):
    """Server auth. The open core supports ``none`` and ``basic`` only."""

    mode: Literal["none", "basic"] = "none"


class ServerConfig(_Strict):
    """Output/serving configuration and runtime mode."""

    mode: Literal["daemon", "on_demand", "mcp", "cli"] = "daemon"
    host: str = "127.0.0.1"
    port: int = 8080
    # Daemon mode only: seconds between successive health analyses.
    interval_seconds: int = 300
    auth: ServerAuthConfig = Field(default_factory=ServerAuthConfig)


class NotificationConfig(_Open):
    """A notification target. Backend-specific keys (``*_env``) are preserved."""

    type: str


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
class AgentConfig(_Strict):
    """Agent persona and reasoning bounds, tunable within guardrails."""

    persona: str = (
        "You are a production health analyst. You observe metrics, logs, and "
        "knowledge context, and you report findings clearly. You do not take "
        "actions unless explicitly permitted and approved."
    )
    max_reasoning_steps: int = 10


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------
class TendwellConfig(_Strict):
    """The complete, validated configuration for one Tendwell deployment."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    data_sources: list[DataSourceConfig] = Field(default_factory=list)
    slos: list[SLO] = Field(default_factory=list)
    context: ContextConfig = Field(default_factory=ContextConfig)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    notifications: list[NotificationConfig] = Field(default_factory=list)
    agent: AgentConfig = Field(default_factory=AgentConfig)

    def egress_targets(self) -> list[tuple[str, str]]:
        """Return ``(component, endpoint)`` pairs that point off-host.

        Used at startup to warn explicitly when the operator has opted out of
        the local-first default by pointing a backend at a remote address. An
        empty list means the deployment makes no off-host calls.
        """
        targets: list[tuple[str, str]] = []

        def check(component: str, endpoint: str | None) -> None:
            if not endpoint:
                return
            host = urlparse(endpoint).hostname
            if host is None or host in LOCAL_HOSTS:
                return
            targets.append((component, endpoint))

        check("llm", self.llm.base_url)
        check("embeddings", self.embeddings.base_url)
        for source in self.data_sources:
            check(f"data_source:{source.name}", source.endpoint)
        # A non-chroma vector store, or a chroma store with a URL-style path,
        # may reach off-host; flag remote-looking vector store paths.
        store_path = self.context.vector_store.path
        if "://" in store_path:
            check("vector_store", store_path)
        return targets
