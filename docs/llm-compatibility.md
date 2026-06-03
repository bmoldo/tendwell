# LLM runtime compatibility

Tendwell talks to any OpenAI-compatible chat completions endpoint through a
single client (`OpenAICompatibleLLMBackend`), selected by `base_url`. CI proves
the client's logic against fakes; it cannot prove how a real runtime behaves.
This matrix records real-runtime validation.

## How to read this

- `native tool calling` - whether the runtime/model reliably returns native
  `tool_calls`. If not, set `capabilities.native_tool_calling: false` and the
  agent uses the prompt-based ReAct fallback, which works without native tool
  support.
- `recommended path` - what to configure for that runtime/model.

## Status

Operator-run. The sandbox that builds Tendwell cannot reach a model, so the rows
below are templates to be filled in by running the demo against each runtime:

```
tendwell run --config examples/demo.yaml         # expects native tool calling
tendwell run --config examples/demo-react.yaml    # forces the ReAct fallback
```

For each runtime/model, run both and record whether the native path produced a
coherent report, whether the fallback did, and any quirks (context limits,
tool-call formatting, latency).

## Matrix

| Runtime  | Model            | Native tool calling | Recommended path | Notes |
|----------|------------------|---------------------|------------------|-------|
| Ollama   | qwen2.5:14b      | _to verify_         | _to verify_      |       |
| Ollama   | llama3.1:8b      | _to verify_         | _to verify_      |       |
| vLLM     | (OpenAI-compat)  | _to verify_         | _to verify_      |       |
| LiteLLM  | (proxy to any)   | _to verify_         | _to verify_      |       |

## Guidance pending data

- Smaller models (roughly 8B and under) are the most likely to need the ReAct
  fallback; expect to set `native_tool_calling: false` for them.
- A LiteLLM proxy is a convenient single `base_url` that routes to Ollama, vLLM,
  Bedrock, and others; Tendwell does not require it but works behind it.
- Embeddings follow the same pattern: any OpenAI-compatible embeddings endpoint,
  local by default.
