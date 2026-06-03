"""Exhaustive unit tests for the ReAct parser.

This is the highest-risk surface: small local models emit malformed text in many
ways, and every one must become a clean parse error (later a corrective retry),
never a crash.
"""

from __future__ import annotations

from tendwell.llm.react import StepKind, parse_react


def test_well_formed_action() -> None:
    step = parse_react(
        "Thought: I should look at the snapshot\nAction: get_health_snapshot\nAction Input: {}"
    )
    assert step.kind is StepKind.ACTION
    assert step.action_name == "get_health_snapshot"
    assert step.action_input == {}
    assert step.thought == "I should look at the snapshot"


def test_well_formed_action_with_args() -> None:
    step = parse_react(
        'Action: query_metrics\nAction Input: {"source": "demo", "query_id": "error_rate"}'
    )
    assert step.kind is StepKind.ACTION
    assert step.action_name == "query_metrics"
    assert step.action_input == {"source": "demo", "query_id": "error_rate"}


def test_well_formed_final_answer() -> None:
    step = parse_react("Thought: done\nFinal Answer: The service is healthy.")
    assert step.kind is StepKind.FINAL
    assert step.final_answer == "The service is healthy."


def test_multiline_final_answer() -> None:
    step = parse_react("Final Answer: line one\nline two\nline three")
    assert step.kind is StepKind.FINAL
    assert step.final_answer == "line one\nline two\nline three"


def test_garbage_is_error() -> None:
    step = parse_react("I think everything looks fine, no structure here.")
    assert step.kind is StepKind.ERROR
    assert step.error is not None


def test_invalid_json_input_is_error() -> None:
    step = parse_react("Action: query_metrics\nAction Input: {not valid json}")
    assert step.kind is StepKind.ERROR
    assert "JSON" in (step.error or "")


def test_non_object_json_input_is_error() -> None:
    step = parse_react('Action: query_metrics\nAction Input: ["a", "b"]')
    assert step.kind is StepKind.ERROR
    assert "object" in (step.error or "")


def test_action_without_input_is_error() -> None:
    step = parse_react("Action: get_health_snapshot")
    assert step.kind is StepKind.ERROR
    assert "Action Input" in (step.error or "")


def test_empty_final_answer_is_error() -> None:
    step = parse_react("Thought: hmm\nFinal Answer:   ")
    assert step.kind is StepKind.ERROR


def test_both_action_and_final_is_ambiguous_error() -> None:
    step = parse_react("Action: get_health_snapshot\nAction Input: {}\nFinal Answer: also done")
    assert step.kind is StepKind.ERROR
    assert "both" in (step.error or "").lower()


def test_code_fenced_output_is_tolerated() -> None:
    step = parse_react(
        "```\nThought: drilling in\nAction: search_knowledge\n"
        'Action Input: {"query": "error rate"}\n```'
    )
    assert step.kind is StepKind.ACTION
    assert step.action_name == "search_knowledge"
    assert step.action_input == {"query": "error rate"}


def test_preamble_before_block_is_tolerated() -> None:
    step = parse_react(
        "Sure, here is my next step.\n\n"
        "Thought: check metrics\n"
        "Action: query_metrics\n"
        'Action Input: {"source": "demo", "query_id": "latency_p99"}'
    )
    assert step.kind is StepKind.ACTION
    assert step.action_input == {"source": "demo", "query_id": "latency_p99"}
