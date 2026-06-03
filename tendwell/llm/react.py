"""Strict parsing for the prompt-based ReAct fallback.

Small local models drive the fallback by emitting plain text in a fixed format.
This module is pure (no I/O, no model, no tool execution) so the parser can be
exercised exhaustively in unit tests. The loop that calls it lives in
``tendwell.core.reasoning``.

The model must emit exactly one of:

    Thought: <reasoning>
    Action: <tool_name>
    Action Input: <single-line JSON object>

or, to finish:

    Thought: <reasoning>
    Final Answer: <answer>

Anything else is a parse error, which the loop turns into a corrective
observation and a retry rather than a crash.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from tendwell.interfaces.llm import ToolSpec

_ACTION = re.compile(r"^[ \t]*Action[ \t]*:[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_ACTION_INPUT = re.compile(r"^[ \t]*Action Input[ \t]*:[ \t]*(.*)$", re.MULTILINE)
_FINAL = re.compile(r"^[ \t]*Final Answer[ \t]*:", re.MULTILINE)
_THOUGHT = re.compile(r"^[ \t]*Thought[ \t]*:[ \t]*(.*)$", re.MULTILINE)


class StepKind(StrEnum):
    """The outcome of parsing one model response."""

    ACTION = "action"
    FINAL = "final"
    ERROR = "error"


@dataclass(frozen=True)
class ReActStep:
    """A parsed ReAct step.

    ``kind`` selects which fields are meaningful: ``ACTION`` populates
    ``action_name`` and ``action_input``; ``FINAL`` populates ``final_answer``;
    ``ERROR`` populates ``error`` with a human-readable reason.
    """

    kind: StepKind
    thought: str | None = None
    action_name: str | None = None
    action_input: dict[str, object] | None = None
    action_input_raw: str | None = None
    final_answer: str | None = None
    error: str | None = None


def _strip_fences(text: str) -> str:
    """Drop code-fence lines and surrounding blank padding."""
    lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
    return "\n".join(lines).strip()


def _first_thought(text: str) -> str | None:
    match = _THOUGHT.search(text)
    return match.group(1).strip() if match else None


def parse_react(text: str) -> ReActStep:
    """Parse one model response into a :class:`ReActStep`.

    Tolerates code fences, leading preamble, and surrounding whitespace. When
    ambiguous (both an action and a final answer present) it returns an error
    step rather than guessing.
    """
    cleaned = _strip_fences(text)
    thought = _first_thought(cleaned)

    action_match = _ACTION.search(cleaned)
    final_match = _FINAL.search(cleaned)

    if action_match and final_match:
        return ReActStep(
            kind=StepKind.ERROR,
            thought=thought,
            error="response contains both an Action and a Final Answer; emit exactly one",
        )

    if final_match:
        answer = cleaned[final_match.end() :].strip()
        if not answer:
            return ReActStep(
                kind=StepKind.ERROR,
                thought=thought,
                error="'Final Answer:' was present but empty",
            )
        return ReActStep(kind=StepKind.FINAL, thought=thought, final_answer=answer)

    if action_match:
        action_name = action_match.group(1).strip()
        input_match = _ACTION_INPUT.search(cleaned)
        if input_match is None:
            return ReActStep(
                kind=StepKind.ERROR,
                thought=thought,
                error="'Action:' was present but no 'Action Input:' line followed",
            )
        raw = input_match.group(1).strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return ReActStep(
                kind=StepKind.ERROR,
                thought=thought,
                error=f"'Action Input' must be a single-line JSON object; got: {raw!r}",
            )
        if not isinstance(parsed, dict):
            return ReActStep(
                kind=StepKind.ERROR,
                thought=thought,
                error="'Action Input' must be a JSON object (a mapping of argument names)",
            )
        return ReActStep(
            kind=StepKind.ACTION,
            thought=thought,
            action_name=action_name,
            action_input=parsed,
            action_input_raw=raw,
        )

    return ReActStep(
        kind=StepKind.ERROR,
        thought=thought,
        error="no 'Action'/'Action Input' or 'Final Answer' found in the response",
    )


def format_instructions(tools: Sequence[ToolSpec]) -> str:
    """Build the strict-format system instructions for the fallback path."""
    lines = [
        "You are driving tools using a strict text protocol. On each turn emit "
        "EXACTLY ONE of the following, and nothing else.",
        "",
        "To call a tool:",
        "Thought: <your reasoning>",
        "Action: <one tool name from the list below>",
        'Action Input: <a single-line JSON object of arguments, e.g. {"query_id": "error_rate"}>',
        "",
        "To finish:",
        "Thought: <your reasoning>",
        "Final Answer: <your complete answer>",
        "",
        "Rules:",
        "- Never emit both an Action and a Final Answer in the same turn.",
        "- Action Input must be valid JSON on a single line.",
        "- After each Action you will receive an Observation; use it on the next turn.",
        "",
        "Available tools:",
    ]
    for tool in tools:
        properties = tool.parameters.get("properties", {})
        arg_names = ", ".join(properties) if isinstance(properties, dict) else ""
        lines.append(f"- {tool.name}({arg_names}): {tool.description}")
    return "\n".join(lines)


def corrective_observation(error: str) -> str:
    """The observation appended after a malformed response, asking for a retry."""
    return (
        f"Your previous response could not be parsed: {error}. "
        "Respond again using the exact format: a 'Thought:' line followed by "
        "either an 'Action:' and 'Action Input:' (single-line JSON), or a "
        "'Final Answer:'. Emit exactly one of the two."
    )
