# Bring your own LLM

Tendwell talks to any OpenAI-compatible chat completions endpoint through a
single client, selected entirely by `llm.base_url`. There is no per-vendor code
path: if a runtime speaks the OpenAI chat completions API, Tendwell can drive it.
This works with Ollama, vLLM, llama.cpp's server, LocalAI, and a LiteLLM proxy
that fronts any of them.

By default everything stays local. The default `base_url`
(`http://localhost:11434/v1`) points at a local Ollama. Point a `base_url` at a
non-localhost address and Tendwell warns you, loudly, at startup.

## The core fields

The LLM is configured under `llm:`:

- `llm.base_url` -- the OpenAI-compatible endpoint to call.
- `llm.model` -- the model id to request from that endpoint.
- `llm.api_key_env` -- the name of an environment variable holding the API key.
  This is optional for local runtimes that need no key. Never inline a key; only
  ever name the env var that holds it.

```yaml
llm:
  base_url: http://localhost:11434/v1
  model: qwen2.5:14b
  # api_key_env: LLM_API_KEY   # only if the runtime requires a key
```

## Native tool calling and the ReAct fallback

The agent uses tool calls to fetch signal and retrieve context. Many small models
are unreliable at native tool calling. Tendwell handles this with one switch:

- `llm.capabilities.native_tool_calling` (default `true`) -- whether the model is
  trusted to return native `tool_calls`.
- If you set it `false`, Tendwell uses a prompt-based ReAct fallback with strict
  output parsing and bounded retries. The tools are the same and the result is the
  same; only the prompting differs.
- `llm.fallback_max_retries` (default `2`) -- how many times a single malformed
  step is re-prompted before the agent degrades gracefully.

```yaml
llm:
  base_url: http://localhost:11434/v1
  model: llama3.1:8b
  capabilities:
    native_tool_calling: false
  fallback_max_retries: 2
```

If you are unsure whether a model needs the fallback, run it both ways and compare
the report. See the compatibility matrix below.

## Embeddings

Embeddings follow the same pattern under `embeddings:`, with their own
`base_url`, `model`, and `api_key_env`. They default to a local model.

```yaml
embeddings:
  base_url: http://localhost:11434/v1
  model: nomic-embed-text
  # api_key_env: EMBEDDINGS_API_KEY
```

## No-network options for demos and tests

Two providers run with no network at all, which is what the instant demo tier and
the test suite use:

- `llm.provider: stub` -- a no-network stub model. It produces a real report with
  deterministic facts and a fixed narrative.
- `embeddings.provider: hash` -- a deterministic, no-network embedder.

```yaml
llm:
  provider: stub
embeddings:
  provider: hash
```

## Runtime config snippets

### Ollama

```yaml
llm:
  base_url: http://localhost:11434/v1
  model: qwen2.5:14b
embeddings:
  base_url: http://localhost:11434/v1
  model: nomic-embed-text
```

### vLLM

vLLM serves an OpenAI-compatible endpoint. Point `base_url` at it and set `model`
to the served model id. If vLLM is configured to require an API key, name the env
var that holds it.

```yaml
llm:
  base_url: http://localhost:8000/v1
  model: Qwen/Qwen2.5-14B-Instruct
  api_key_env: LLM_API_KEY
```

### LiteLLM proxy

A LiteLLM proxy is a single `base_url` that routes to Ollama, vLLM, and other
backends. Tendwell does not require it, but works behind it. Set `model` to the
model name the proxy exposes.

```yaml
llm:
  base_url: http://localhost:4000/v1
  model: my-routed-model
  api_key_env: LLM_API_KEY
```

## Compatibility matrix

The runtime compatibility matrix lives at
[docs/llm-compatibility.md](llm-compatibility.md). It records, per
runtime x model, whether native tool calling is reliable and what to configure,
with notes. It is operator-validated: CI proves the client's logic against fakes,
but only a real runtime can prove how it behaves in practice. That matrix is the
evidence behind the "any local LLM" claim -- consult it before committing to a
specific runtime and model, and add a row when you validate a new one.
