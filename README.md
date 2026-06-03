# Tendwell

**Self-hosted, local-first AgentOps for production health.** Tendwell is an agent
that watches your production signals and operational knowledge, reasons over them
with a local LLM, and explains what it finds in plain language - then, only when
you allow it, proposes remediations that a human approves and a tamper-evident
audit log records.

It is built for the teams that cannot send production data to someone else's
cloud: **security-conscious and regulated environments**. By default nothing
leaves your infrastructure - not the metrics, not the runbooks, not the model.

- **Local-first by default.** No egress out of the box, including the LLM and
  embeddings. Point a backend off-host and Tendwell warns you, loudly, at startup.
- **The LLM never executes.** It can only propose. Deterministic validation and a
  human approval gate sit between any proposal and any change. Every step is an
  append-only, hash-chained audit event that cannot be silenced.
- **Bring your own everything.** Any OpenAI-compatible model (Ollama, vLLM,
  llama.cpp, LocalAI, LiteLLM), pluggable data sources, and - for actions - your
  own executor. The open core ships no real executor, so it cannot mutate
  anything until you wire one in.

Free and Apache-2.0. Not a SaaS. Not tied to any cloud, vendor, or monitoring
stack.

## See it work in under a minute

The instant demo runs against a synthetic production scenario with a stub model -
no model download, no external services, no egress:

```
git clone https://github.com/bmoldo/tendwell
cd tendwell
docker compose up
```

You get a real health report immediately. The SLO evaluation and the cited
runbooks are real; only the narrative is a stub until you add a model:

```
[CRITICAL] Production health
2 SLO(s) breached.
SLOs:
  - availability [breached]: error_rate=0.057, healthy below 0.01
  - latency [breached]: latency_p99=0.92, healthy below 0.5
Citations:
  - error-rate-runbook.md
  - latency-postmortem.md
```

For genuine model-driven narrative, add the Ollama profile - this pulls a small
model once (a few hundred MB to ~1 GB, the honest one-time cost):

```
docker compose --profile model up
```

Then point it at your own stack: edit a config to use the Prometheus source and
your local model. See the [quickstart](docs/quickstart.md).

## How it works

A deployment is one YAML file plus injected secrets; the code carries zero
environment-specific values. Four layers sit behind stable interfaces, so you can
swap any of them without touching the core:

- **Data sources** - where live signal comes from. Prometheus, Loki, and a
  generic HTTP/JSON adapter today, normalized into one result shape. A failing
  source degrades an SLO to `unknown`; it never crashes the run.
- **LLM backend** - any OpenAI-compatible endpoint via a configurable `base_url`.
  Small models that are weak at native tool calls fall back to a prompt-based
  ReAct loop with strict parsing.
- **Context store** - runbooks and postmortems embedded locally and retrieved by
  relevance. Citations come only from retrieved chunks, so the model cannot
  invent a source.
- **Output / action surface** - how findings are served and, only when you
  explicitly enable it, how gated actions are taken.

The agent is deliberately hybrid: a deterministic pre-fetch evaluates every SLO
without the LLM, so even a weak model that fails every tool call still produces a
correct status. The model adds interpretation and correlation on top.

## The security model is the product

For a regulated buyer this is the part that matters. Mutating production runs
through four separated stages, with a human and deterministic checks between the
model and any change:

1. **Propose** - the LLM emits a structured proposal. It records intent and
   executes nothing.
2. **Validate** - deterministic checks (allowlist, argument schema, scope, rate
   limit, circuit breaker, kill switch) run before a human is ever paged.
3. **Approve** - a human approves out-of-band, with identity and time captured.
   The model has no tool, endpoint, or path to approve.
4. **Execute** - a separate, non-LLM executor acts per target, with write-scoped
   credentials held only for that run. Partial failure is first-class.

Read-only is the default and **the open core ships no real executor**: with no
action surface configured, the agent is structurally unable to change anything.
Audit logging is append-only, hash-chained, and cannot be disabled. See the
[security model](docs/security-model.md).

## Documentation

- [Quickstart](docs/quickstart.md) - zero to a working Tendwell.
- [Configuration reference](docs/configuration.md) - every field and what is
  locked by design.
- [Security model](docs/security-model.md) - the full version of the above.
- [Bring your own LLM](docs/bring-your-own-llm.md) - any OpenAI-compatible
  runtime, plus the compatibility matrix.
- [Add a data source](docs/add-a-data-source.md) - implement the `DataSource`
  interface.
- [Register an executor](docs/register-an-executor.md) - wire a real executor
  with the safety contract.
- [Contributing](CONTRIBUTING.md).
- Deploy: a [Helm chart](deploy/helm) and a [Terraform module](deploy/terraform).

## Development

```
uv sync --dev
uv run ruff check . && uv run ruff format --check .
uv run mypy tendwell
uv run pytest
```

## License

Apache 2.0. See [`LICENSE`](LICENSE). The free core stays genuinely capable; it is
never crippled to sell an upgrade.
