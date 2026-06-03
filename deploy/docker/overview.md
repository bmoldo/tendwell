# Tendwell

Self-hosted, local-first AgentOps for production health. Tendwell watches your
production signals and operational knowledge, reasons over them with a local LLM,
and explains what it finds in plain language - then, only when you allow it,
proposes remediations that a human approves and a tamper-evident audit log
records.

Built for teams that cannot send production data to someone else's cloud. By
default nothing leaves your infrastructure - not the metrics, not the runbooks,
not the model.

## Quick start

See it work immediately. The default command runs an instant demo against a
synthetic production scenario with a stub model - no model download, no external
services, no egress:

```
docker run --rm bmoldovan/tendwell
```

You get a real health report: the SLO evaluation and the cited runbooks are real;
only the narrative is a stub until you add a model.

Point it at your own config:

```
docker run --rm -v "$PWD/tendwell.yaml:/etc/tendwell/tendwell.yaml:ro" \
  bmoldovan/tendwell run --config /etc/tendwell/tendwell.yaml
```

## What it is

- **Local-first by default.** No egress out of the box, including the LLM and
  embeddings. Point a backend off-host and Tendwell warns you at startup.
- **The LLM never executes.** It can only propose. Deterministic validation and a
  human approval gate sit between any proposal and any change. Every step is an
  append-only, hash-chained audit event that cannot be silenced.
- **Bring your own everything.** Any OpenAI-compatible model (Ollama, vLLM,
  llama.cpp, LocalAI, LiteLLM), pluggable data sources (Prometheus, Loki, generic
  HTTP/JSON), and - for actions - your own executor. The open core ships no real
  executor, so it cannot mutate anything until you wire one in.

## Tags

- `latest`, `0.0.1` - linux/amd64.

The image runs as a non-root user and serves no network port in the default
demo.

## Links

- Source and documentation: https://github.com/bmoldo/tendwell
- Overview and the story: https://reops.tech/tendwell/

Free and Apache-2.0.
