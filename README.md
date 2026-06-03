# Tendwell

Tendwell is a self-hostable AgentOps tool for production AI reliability. It
tends your systems and keeps them well: it observes live signals and
operational knowledge, reasons over them with a local LLM, and reports on the
health of production in plain language.

It is built for self-hosted, security-conscious, and regulated environments.
The headline guarantee: **local-first, your data never leaves your
infrastructure** by default, including the LLM and embeddings.

> Status: early development. Phase 0 (interfaces and configuration) is in place;
> the Prometheus adapter, LLM backend, context store, and demo stack land next.
> See the build roadmap in [`CLAUDE.md`](CLAUDE.md).

## What it is

- A self-hostable agent that monitors production health, retrieves the relevant
  runbooks and history, and explains what it finds.
- Local-first by default: out of the box, no data leaves the operator's host.
  Pointing a backend at a remote address is possible but is an explicit,
  warned choice.
- Configuration-driven: a single deployment is defined by one config file plus
  injected secrets. The code carries zero environment-specific values.
- Secure by default: read-only out of the box. The agent observes and reports;
  it cannot mutate anything unless explicitly enabled and approved.

It is not a SaaS, and it is not tied to any specific company, cloud, or
monitoring stack. Self-hosting is always first-class and free (Apache 2.0).

## Architecture

Four layers sit behind stable interfaces (`tendwell/interfaces/`); concrete
adapters implement them and the core agent loop depends only on the contracts:

- `DataSource` - where live signal comes from (first adapter: Prometheus).
- `LLMBackend` - the reasoning engine, any OpenAI-compatible endpoint (Ollama,
  vLLM, llama.cpp, LocalAI, LiteLLM).
- `ContextStore` - embedded knowledge (runbooks, postmortems, topology),
  retrieved by relevance (first store: Chroma).
- `OutputSink` / `ActionSurface` - how findings are served and, only when
  explicitly permitted, how gated actions are taken.

Two kinds of context are kept separate at reasoning time: live context, pulled
per query and never stored, and knowledge context, embedded and retrieved by
relevance.

## Configuration

A deployment is one YAML file plus injected secrets. See
[`tendwell.example.yaml`](tendwell.example.yaml) for the full, annotated shape.
Secrets are never inline; config references the environment variable that holds
each credential.

Validate a config file:

```
uv run tendwell validate tendwell.example.yaml
```

The default configuration is local-first; if you point the LLM, embeddings, or a
data source at a remote address, Tendwell warns you explicitly.

## Development

```
uv sync --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy tendwell
uv run pytest
```

## License

Apache 2.0. See [`LICENSE`](LICENSE). The free core stays genuinely capable.
