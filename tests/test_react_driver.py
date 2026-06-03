"""Driver tests: retry recovery, graceful degradation, and step caps.

These exercise the ReAct loop end to end with a scripted backend and the real
tool executor, with no model and no network.
"""

from __future__ import annotations

from tendwell.core.reasoning import NativeToolDriver, ReActDriver
from tendwell.llm.fake import FakeLLMBackend
from tests.conftest import synthetic_executor, text_response, tool_response


async def test_react_happy_path() -> None:
    backend = FakeLLMBackend(
        responses=[
            text_response("Thought: look\nAction: get_health_snapshot\nAction Input: {}"),
            text_response("Thought: done\nFinal Answer: All healthy."),
        ],
        native_tool_calling=False,
    )
    driver = ReActDriver(backend)
    result = await driver.run("persona", "task", synthetic_executor(), max_steps=6)
    assert result.truncated is False
    assert result.answer == "All healthy."


async def test_react_recovers_from_malformed_then_valid() -> None:
    backend = FakeLLMBackend(
        responses=[
            text_response("this is not a valid react step at all"),
            text_response("Thought: recovered\nFinal Answer: Recovered fine."),
        ],
        native_tool_calling=False,
    )
    driver = ReActDriver(backend, max_retries=2)
    result = await driver.run("persona", "task", synthetic_executor(), max_steps=6)
    assert result.truncated is False
    assert result.answer == "Recovered fine."
    # One malformed retry plus one good response.
    assert len(backend.calls) == 2


async def test_react_degrades_after_retry_budget() -> None:
    backend = FakeLLMBackend(
        responses=[text_response("persistently malformed nonsense")],
        native_tool_calling=False,
    )
    driver = ReActDriver(backend, max_retries=2)
    result = await driver.run("persona", "task", synthetic_executor(), max_steps=6)
    assert result.truncated is True
    assert result.note is not None
    # Initial attempt plus 2 retries before degrading, all on one step.
    assert len(backend.calls) == 3


async def test_react_stops_at_step_cap() -> None:
    # Always a valid action, never a final answer -> must stop at the step cap.
    backend = FakeLLMBackend(
        responses=[text_response("Action: get_health_snapshot\nAction Input: {}")],
        native_tool_calling=False,
    )
    driver = ReActDriver(backend)
    result = await driver.run("persona", "task", synthetic_executor(), max_steps=3)
    assert result.truncated is True
    assert result.steps == 3
    assert len(backend.calls) == 3


async def test_native_happy_path() -> None:
    backend = FakeLLMBackend(
        responses=[
            tool_response("get_health_snapshot", {}),
            text_response("Everything looks fine."),
        ],
        native_tool_calling=True,
    )
    driver = NativeToolDriver(backend)
    result = await driver.run("persona", "task", synthetic_executor(), max_steps=6)
    assert result.truncated is False
    assert result.answer == "Everything looks fine."


async def test_native_stops_at_step_cap() -> None:
    backend = FakeLLMBackend(
        responses=[tool_response("get_health_snapshot", {})],
        native_tool_calling=True,
    )
    driver = NativeToolDriver(backend)
    result = await driver.run("persona", "task", synthetic_executor(), max_steps=2)
    assert result.truncated is True
    assert result.steps == 2


async def test_invalid_tool_input_becomes_observation_not_crash() -> None:
    # query_metrics with a missing required field must come back as an error
    # observation, and the loop continues to a clean final answer.
    backend = FakeLLMBackend(
        responses=[
            text_response('Action: query_metrics\nAction Input: {"source": "demo"}'),
            text_response("Final Answer: handled the tool error gracefully"),
        ],
        native_tool_calling=False,
    )
    driver = ReActDriver(backend)
    result = await driver.run("persona", "task", synthetic_executor(), max_steps=6)
    assert result.truncated is False
    assert result.answer == "handled the tool error gracefully"
