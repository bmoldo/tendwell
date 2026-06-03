# Configuration reference

A Tendwell deployment is a single YAML file plus secrets injected from the
environment. Secrets are never written inline; they are referenced by the name
of an environment variable. The code carries no environment-specific values.

The annotated template `tendwell.example.yaml` in the repo root is kept in sync
with this surface and is the recommended starting point.

Validate any config before running it:

```
tendwell validate <config.yaml>
```

`validate` checks the config and prints any local-first egress warnings (see
"Locked by design" below). The example configs in `examples/` show complete,
working files for each tier.

This reference has one section per top-level block.

## llm

The LLM backend. Any OpenAI-compatible endpoint.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `provider` | `openai` or `stub` | `openai` | Backend selector. `stub` is a no-network demo backend. |
| `base_url` | string | `http://localhost:11434/v1` | OpenAI-compatible endpoint. The default targets a local Ollama. |
| `model` | string | `qwen2.5:14b` | Model name. |
| `api_key_env` | string | (unset) | Name of the environment variable holding the API key. Optional for local backends. |
| `context_window` | integer | `32768` | Model context window in tokens. |
| `params` | map | `{temperature: 0.1}` | Provider parameters passed through to the backend. |
| `capabilities.native_tool_calling` | boolean | `true` | When `false`, Tendwell uses a prompt-based ReAct fallback instead of native tool calls. |
| `fallback_max_retries` | integer | `2` | Maximum retries for the ReAct fallback parser. |

## embeddings

The embedding backend used to index and retrieve knowledge context.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `provider` | `openai` or `hash` | `openai` | Backend selector. `hash` is a deterministic, no-network embedder. |
| `base_url` | string | (provider default) | OpenAI-compatible embeddings endpoint. |
| `model` | string | `nomic-embed-text` | Embedding model name. |
| `api_key_env` | string | (unset) | Name of the environment variable holding the API key. Optional for local backends. |

## data_sources

A list of pluggable adapters that supply live signal. Each entry has a `name`,
a `type` that selects the adapter, and adapter-specific fields. Common fields:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | string | (required) | Identifier for the source. |
| `type` | string | (required) | Adapter selector: `prometheus`, `loki`, `http_json`, or `synthetic`. |
| `endpoint` | string | (optional) | The source URL. Not used by `synthetic`. |
| `auth.mode` | `none`, `bearer`, or `basic` | -- | Authentication mode for the source. |
| `auth.token_env` | string | -- | Name of the environment variable holding the token, used when `auth.mode` is not `none`. |

Each adapter then defines its own `queries`. Every query has an `id`; the `id`
is what an SLO refers to as its `metric`.

### prometheus

```yaml
queries:
  - id: error_rate
    promql: 'sum(rate(http_requests_total{status=~"5.."}[5m]))'
```

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Query identifier. |
| `promql` | string | PromQL expression to evaluate. |

### loki

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `id` | string | -- | Query identifier. |
| `logql` | string | -- | LogQL expression. |
| `limit` | integer | `100` | Maximum number of entries to return. |
| `range_seconds` | integer | `300` | Lookback window in seconds. |

### http_json

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Query identifier. |
| `path` | string | Request path appended to the source `endpoint`. |
| `value_path` | string | Dot-path into the JSON response that selects the value, for example `data.0.value`. |

### synthetic

A deterministic generator used by the demos. Contacts no external system.

| Field | Type | Meaning |
| --- | --- | --- |
| `scenario` | `healthy` or `degraded` | Which scenario to generate. |
| `seed` | integer | Seed for deterministic output. |
| `queries` | list of `{id}` | The query ids to produce values for. |

## slos

A list of service-level objectives evaluated deterministically, without the
LLM.

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | SLO name. |
| `metric` | string | A query `id` from a configured data source. |
| `threshold` | float | The threshold value. |
| `direction` | `above` or `below` | Names the HEALTHY side of the threshold. `below` means healthy while under the threshold; the SLO breaches above it. `above` is the mirror. |

## context

Knowledge context: runbooks, postmortems, and topology, embedded locally and
retrieved by relevance.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `vector_store.type` | `chroma` or `memory` | `chroma` | Vector store backend. |
| `vector_store.path` | string | `./data/vectors` | Persistence path for `chroma`. An empty path, or the `memory` type, runs the store in-process with no persistence. |
| `loaders` | list | -- | Context loaders (see below). |

Each loader:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `type` | `markdown` | -- | Loader type. |
| `path` | string | -- | Directory of source documents. |
| `refresh` | integer | `3600` | Re-index interval in seconds. |
| `chunk_size` | integer | `800` | Chunk size in characters. |
| `chunk_overlap` | integer | `150` | Overlap between consecutive chunks. |

## permissions

Action posture and the gating around any action. Read-only by default; actions
are opt-in.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `mode` | `read_only` or `actions_enabled` | `read_only` | Whether any action surface is active at all. |
| `actions` | list | `[]` | The allowlist of permitted actions (see below). |

### permissions.actions

Each action is individually allowed and gated.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | string | (required) | Action name. Names containing `config`, `allowlist`, `audit`, `approval`, `approve`, `credential`, or `secret` are rejected (see "Locked by design"). |
| `require_approval` | boolean | `true` | Whether human approval is required. Setting `false` is rejected; auto-approval is not available. |
| `scope` | list | -- | The allowed targets this action may touch. |
| `parameters` | map | -- | Parameter schema: name maps to `{type, required}`, where `type` is `string`, `integer`, `number`, or `boolean`. |
| `idempotent` | boolean | `false` | Whether the operation is safe to repeat. Non-idempotent operations are never silently retried. |
| `max_targets` | integer or null | -- | Upper bound on targets per invocation. `null` means no fixed bound. |

### permissions.safety

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `rate_limit.max_actions` | integer | `5` | Maximum actions per window. |
| `rate_limit.window_seconds` | integer | `60` | Rate-limit window in seconds. |
| `circuit_breaker.failure_threshold` | integer | `3` | Consecutive failures that trip the breaker. |
| `kill_switch_file` | string | (optional) | A path whose presence halts all executions, pending and future. |

### permissions.audit

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `enabled` | boolean | `true` | Audit logging. Setting `false` is rejected; audit is always on. |

## server

How findings are served.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `mode` | `daemon`, `on_demand`, `mcp`, or `cli` | `daemon` | Serving mode. |
| `host` | string | `127.0.0.1` | Bind address. |
| `port` | integer | `8080` | Bind port. |
| `auth.mode` | `none` or `basic` | -- | Authentication mode for the server. |

## agent

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `persona` | string | -- | Framing for the agent, tunable within the guardrails. |
| `max_reasoning_steps` | integer | `10` | Upper bound on reasoning steps per run. |

## Locked by design

Some defaults and rejections are deliberate and cannot be configured away. Each
is a structural guarantee, not a convenience.

- **Read-only is the default posture.** `permissions.mode` defaults to
  `read_only`. A fresh config, and any config that does not opt in, can observe
  and report but cannot change anything. Enabling actions is a deliberate,
  explicit act.

- **Audit cannot be disabled.** `permissions.audit.enabled: false` is rejected.
  The audit log is append-only and hash-chained, so that the record of what was
  attempted and what completed is always present and tamper-evident. Allowing it
  to be turned off would defeat that guarantee.

- **No auto-approval.** `require_approval: false` is rejected. The open core has
  no auto-approval path. Every action that runs has a human approval, captured
  with identity and timestamp, between the model's proposal and the execution.

- **Local-first by default; egress is announced.** Every default endpoint and
  `base_url` points at localhost, so out of the box no data leaves the host. Any
  non-localhost `base_url` or `endpoint` produces an explicit startup egress
  warning. `tendwell validate` prints these warnings too, so you see them before
  you run. The intent is that data leaving the host is never silent.

- **Reserved action names are rejected.** Action names containing `config`,
  `allowlist`, `audit`, `approval`, `approve`, `credential`, or `secret` are
  rejected. This makes Tendwell's own internals -- its configuration, its
  allowlist, its audit log, its approval gate, and its credentials -- structurally
  untargetable by any action the model might propose.

For the full reasoning behind these guarantees, see `docs/security-model.md`.
