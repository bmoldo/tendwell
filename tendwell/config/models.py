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
    """OpenAI-compatible chat backend configuration."""

    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen2.5:14b"
    api_key_env: str | None = None
    context_window: int = 32768
    params: dict[str, object] = Field(default_factory=_default_llm_params)
    capabilities: Capabilities = Field(default_factory=Capabilities)


class EmbeddingsConfig(_Strict):
    """OpenAI-compatible embeddings backend configuration."""

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
    """Vector store backend. Chroma is the local-first default."""

    type: Literal["chroma", "pgvector", "qdrant"] = "chroma"
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
class ActionConfig(_Strict):
    """An opt-in, scoped, approval-gated action capability."""

    name: str
    require_approval: bool = True
    scope: list[str] = Field(default_factory=list)


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
