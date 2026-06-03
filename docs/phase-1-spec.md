# Tendwell - Phase 1 Implementation Spec

Companion to `CLAUDE.md`. Phase 1 makes the agent run end to end against a
synthetic demo stack with zero real infrastructure, reasoning over live signal
and knowledge context with any OpenAI-compatible local model, including models
with no reliable native tool calling.

## Deliverables

1. The core agent loop (read-only health analysis).
2. `PrometheusDataSource` - first real `DataSource` adapter.
3. `OpenAICompatibleLLMBackend` - the `LLMBackend`, with the ReAct fallback.
4. `ChromaContextStore` + `MarkdownContextLoader`.
5. `SyntheticDataSource` - demo/CI source with healthy and unhealthy scenarios.
6. A runnable `tendwell run` path (on-demand mode) wired to a demo config.

## Core agent loop (hybrid)

1. Pre-fetch (deterministic, no LLM): query each source, evaluate against SLOs,
   assemble a `HealthSnapshot` (per-SLO ok / breached / unknown).
2. Retrieve knowledge context for breaches or the user's question.
3. Reason (LLM): snapshot plus retrieved context as structured input, with a
   small set of read-only tools for drill-down.
4. Emit a `HealthReport`.

Even a weak model that fails every tool call still gets a fully-populated
snapshot, so the basic path degrades to deterministic status plus a plain
summary rather than failing. `max_reasoning_steps` caps the loop; on cap, return
the best report with a truncation note.

Read-only tools (one schema, both paths): `query_metrics`, `search_knowledge`,
`get_health_snapshot`. Invalid tool input returns a structured error observation,
never an exception that aborts the run.

## LLM backend and ReAct fallback

One client targeting a configurable OpenAI-compatible `base_url`. Native path
uses standard tool calling. Fallback path (for models without reliable native
tool calling) is a prompt-driven ReAct loop with strict parsing: tolerate fences
and preamble, reject ambiguous or malformed output as a retryable corrective
observation, degrade gracefully on exceeding retries or the step cap, never raise
for model-format problems. Both paths produce equivalent reports for the same
scenario and tool results.

## Context

`ChromaContextStore` embeds documents via a configurable, OpenAI-compatible
embeddings endpoint (local by default) behind a small client that can be faked.
`MarkdownContextLoader` chunks a directory of markdown with stable ids and
source/heading metadata for citation.

## Gate

- On-demand run yields a coherent report on the unhealthy demo scenario with a
  real local model.
- The same run works with `native_tool_calling: false` (ReAct fallback).
- CI runs the full end-to-end path with a fake LLM and fake embeddings, no
  network, covering both tool paths.
- Prometheus adapter validated against mocked payloads including failure modes; a
  failing source degrades to `unknown`, no crash.
- Citations reference real retrieved chunks; the model cannot invent sources.
- Local-first default: zero egress warnings on the demo config.
- ruff, mypy --strict, pytest, hygiene scan clean.
