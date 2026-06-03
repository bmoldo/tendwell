"""The four stable interfaces that define Tendwell's pluggable layers.

Concrete adapters implement these abstract base classes; the core agent loop
depends only on the interfaces, never on a specific backend.

- ``DataSource``   - where live signal comes from.
- ``LLMBackend``   - the reasoning engine (OpenAI-compatible).
- ``ContextStore`` - embedded knowledge, retrieved by relevance.
- ``OutputSink`` / ``ActionSurface`` - how findings are served and, only when
  explicitly permitted, how gated actions are taken.
"""

from tendwell.interfaces.context_store import (
    ContextLoader,
    ContextStore,
    Document,
    RetrievedChunk,
)
from tendwell.interfaces.data_source import (
    DataSource,
    LogEntry,
    MetricSample,
    QueryResult,
    SignalKind,
)
from tendwell.interfaces.llm import (
    CompletionResult,
    LLMBackend,
    Message,
    Role,
    ToolCall,
    ToolSpec,
)
from tendwell.interfaces.output import (
    ActionOutcome,
    ActionRequest,
    ActionSurface,
    Finding,
    OutputSink,
    Severity,
)

__all__ = [
    "ActionOutcome",
    "ActionRequest",
    "ActionSurface",
    "CompletionResult",
    "ContextLoader",
    # context_store
    "ContextStore",
    # data_source
    "DataSource",
    "Document",
    "Finding",
    # llm
    "LLMBackend",
    "LogEntry",
    "Message",
    "MetricSample",
    # output
    "OutputSink",
    "QueryResult",
    "RetrievedChunk",
    "Role",
    "Severity",
    "SignalKind",
    "ToolCall",
    "ToolSpec",
]
