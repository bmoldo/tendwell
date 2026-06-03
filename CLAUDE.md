# Tendwell

An agentic production-health monitoring tool. It tends your systems and keeps them well: it observes live signals and operational knowledge, reasons over them with a local LLM, and reports on the health of production. Category: AgentOps / production AI reliability, built for self-hosted, security-conscious, and regulated environments.

This file is the source of truth for how Tendwell is built. Read it before making architectural or tooling decisions. The decisions here are deliberate; do not re-litigate them without being asked.

## What Tendwell is (and is not)

- It IS a self-hostable agent that monitors production health, retrieves relevant runbooks and history, and explains what it finds in plain language.
- It IS local-first: by default no data leaves the operator's infrastructure, including the LLM and embeddings.
- It IS configuration-driven: a single deployment is defined by a config file plus injected secrets. The code contains zero environment-specific values.
- It is NOT a SaaS. Self-hosting is always first-class and free.
- It is NOT tied to any specific company, cloud, monitoring stack, or service. No prior employer, environment, hostname, or internal service name appears anywhere in the code, comments, history, or docs.

## Non-negotiable principles

1. Config over code. Anything environment-specific is config, never hardcoded.
2. Local-first by default. The default configuration sends no data off-host. Using a remote model or store is possible but must be an explicit, warned choice.
3. Secure by default. Read-only posture out of the box. The agent observes and reports; it cannot mutate anything unless explicitly enabled and approved.
4. Pluggable behind stable interfaces. Four layers are swappable: data sources, LLM backend, context store, output/action surface. Each sits behind an abstract interface; concrete adapters implement it.
5. Auditable. Any action the agent takes is logged. Audit logging cannot be silenced.

## Tech stack

- Language: Python 3.11+.
- Packaging and env: uv.
- Config: pydantic / pydantic-settings for typed, validated config loaded from YAML plus environment variables.
- API / server: FastAPI (async, typed, auto OpenAPI). Reasonable default; the server layer is thin and sits behind the output interface.
- LLM access: any OpenAI-compatible chat completions endpoint via the `openai` client pointed at a configurable `base_url`. Supports Ollama, vLLM, llama.cpp server, LocalAI, and a LiteLLM proxy. Never hardcode a single runtime.
- Embeddings: configurable OpenAI-compatible embeddings endpoint, defaulting to a local model.
- Vector store: Chroma as the default implementation behind a vector-store interface; design so pgvector and Qdrant can be added.
- Metrics source: Prometheus as the first data-source adapter.
- MCP: Tendwell can run as an MCP server exposing its monitoring capabilities as tools. Use the official Python MCP SDK.
- Lint/format: ruff. Tests: pytest. Types: full type hints, checked with the project's configured type checker.

If a stack choice here proves wrong in practice, raise it rather than silently substituting.

## Repository conventions

- No emojis anywhere: not in code, comments, docstrings, logs, documentation, or commit messages.
- Commit messages: plain, descriptive, imperative mood. Do not add AI tool attribution, "Generated with" footers, or co-author trailers of any kind. Commits read as if written by a human engineer.
- Clean repository. No internal hostnames, company names, client names, or references to any prior or private environment. This is a fresh public project with no inherited history.
- Conventional, readable structure. Small modules, clear names, type hints throughout. Favor clarity over cleverness.
- Every public interface has a docstring. Every adapter documents its config shape.
- Secrets never appear in code, config files, tests, or fixtures. Reference them by environment variable or secret-manager path.

## Architecture

Define the four interfaces as abstract base classes first, before any concrete implementation.

- `DataSource` - fetches live signal. Methods to query metrics/logs/state and return normalized results. First implementation: `PrometheusDataSource`.
- `LLMBackend` - wraps an OpenAI-compatible endpoint. Handles chat completion, tool calling, and a prompt-based ReAct fallback when the model lacks reliable native tool calling (declared via config capability flag).
- `ContextStore` - embeds and retrieves knowledge context (runbooks, postmortems, topology). First implementation: `ChromaContextStore`. Context loaders (markdown directory first) feed it.
- `OutputSink` / action surface - serves findings (daemon, on-demand, MCP, CLI) and, only when permitted, executes gated actions.

Suggested layout:

```
tendwell/
  core/            # agent loop, reasoning orchestration
  interfaces/      # the four abstract base classes
  sources/         # data-source adapters (prometheus, ...)
  llm/             # OpenAI-compatible client, capability handling, ReAct fallback
  context/         # vector store impls + loaders
  output/          # server (FastAPI), MCP server, CLI
  config/          # pydantic models, loading, validation
  audit/           # audit logging (always on for actions)
  demo/            # synthetic metrics generator for zero-infra eval
tests/
deploy/            # docker compose, helm chart, terraform module
```

Separate two kinds of context at reasoning time: live context (pulled per query from data sources, never stored) and knowledge context (embedded, retrieved by relevance).

## Security model

- Default `permissions.mode: read_only`. The agent cannot mutate anything in this mode.
- Actions are opt-in per action, scoped, and human-approval-gated by default. Implement approval as a real gate, not a log line.
- Credentials are least-privilege and injected, never inline.
- Audit logging is always on for any action and cannot be disabled via config. This is intentional; do not add a flag to turn it off.
- The local-first guarantee: the default config performs no off-host calls. If the operator configures a remote LLM, embeddings, or store, surface a clear warning at startup.
- The MCP tool surface respects the same read-only and least-privilege defaults; exposing Tendwell to other agents must not become a privilege-escalation path.

## Configuration surface

Configurable: data sources and their endpoints/queries/thresholds/SLOs; LLM backend, model, params, embedding model; vector store backend and context sources/refresh; notification targets; action capabilities (opt-in, default none); deployment topology and runtime mode; agent persona/prompt framing within guardrails; auth mode (none/basic in the open core).

Locked by design (do not make these configurable): the core agent reasoning loop and orchestration; read-only as the default posture; audit logging for actions (always on); the local-first / no-egress default. Loosening a safe default must always be explicit and logged.

See `tendwell.example.yaml` for the config shape; keep it up to date in the repo root.

## Deployment and run

Run modes: `daemon` (continuous monitoring), `on_demand` (conversational query of current state), `mcp` (MCP server), `cli` (scriptable one-shot).

Deployment targets, in priority order:
1. `docker compose up` bundling Tendwell, a local model runtime, a vector store, and the demo source. This is the five-minute eval path and matters most for adoption.
2. Single container / package for a simple host.
3. Helm chart for Kubernetes.
4. Terraform module.

A stranger should go from zero to a working Tendwell in under ten minutes using only the README.

## Dev workflow

- Format and lint with ruff before committing.
- Type-check the codebase.
- Tests with pytest. New adapters and the agent loop need unit coverage; the demo stack enables end-to-end tests with no real infrastructure.
- Keep the demo synthetic data source working at all times; it is how everyone evaluates and how CI runs e2e.

## License

Apache 2.0. The free core stays genuinely capable; never cripple it to push a paid feature.

## Build roadmap

Build in order; treat each as a checkpoint.

- Phase 0: define the four abstract interfaces and the pydantic config models. No environment-specific anything. Establish repo, license, ruff/pytest/type-check, CI skeleton.
- Phase 1: implement `PrometheusDataSource`, the OpenAI-compatible `LLMBackend` (with ReAct fallback), `ChromaContextStore` + markdown loader, and the synthetic demo source. Get the agent running end-to-end against the demo stack.
- Phase 2: add 2-3 more data-source adapters (e.g. logs, cloud metrics); validate the LLM layer against Ollama, vLLM, and a LiteLLM proxy; implement the full security model (read-only default, gated actions, audit, secrets handling).
- Phase 3: packaging and run experience - docker compose, Helm chart, Terraform module, and the documentation set (quickstart, config reference, security model, bring-your-own-LLM, add-a-data-source).
- Phase 4: launch readiness - the README as positioning (lead with the AgentOps category and the local-first/regulated angle), and a verified no-internal-data check.

## Do not

- Do not add emojis anywhere.
- Do not add AI attribution, co-author trailers, or "Generated with" footers to commits.
- Do not reference any specific company, client, or prior/internal environment.
- Do not make the agent mutate anything by default, or add a way to disable audit logging.
- Do not change the default to send data off-host.
- Do not build a paid tier, SaaS control plane, or license gating in the open core.
- Do not cripple the free core to differentiate a future paid feature.
