"""The two reasoning drivers: native tool calling and the ReAct fallback.

Both drive the same ``ToolExecutor`` over the same tool schemas and return the
same ``DriverResult`` shape, so the agent loop is identical regardless of which
one runs. The only difference is how the model is prompted and how its output is
read back. Neither driver raises for model-format problems: a model that never
finishes degrades to a truncated result.
"""

from __future__ import annotations

from dataclasses import dataclass

from tendwell.core.tools import ToolExecutor, observation_json
from tendwell.interfaces.llm import LLMBackend, Message, Role
from tendwell.llm.react import (
    StepKind,
    corrective_observation,
    format_instructions,
    parse_react,
)


@dataclass(frozen=True)
class DriverResult:
    """Outcome of running a reasoning driver to completion or to a cap."""

    answer: str
    steps: int
    truncated: bool = False
    note: str | None = None


class NativeToolDriver:
    """Drives reasoning with native OpenAI-style tool calling."""

    def __init__(self, llm: LLMBackend) -> None:
        self._llm = llm

    async def run(
        self,
        system_prompt: str,
        user_prompt: str,
        executor: ToolExecutor,
        max_steps: int,
    ) -> DriverResult:
        tools = executor.tool_specs()
        messages: list[Message] = [
            Message(Role.SYSTEM, content=system_prompt),
            Message(Role.USER, content=user_prompt),
        ]
        last_content = ""
        for step in range(max_steps):
            result = await self._llm.complete(messages, tools=tools)
            if result.tool_calls:
                messages.append(
                    Message(
                        Role.ASSISTANT,
                        content=result.content,
                        tool_calls=result.tool_calls,
                    )
                )
                for call in result.tool_calls:
                    observation = await executor.execute(call.name, call.arguments)
                    messages.append(
                        Message(
                            Role.TOOL,
                            content=observation_json(observation),
                            tool_call_id=call.id,
                        )
                    )
                if result.content:
                    last_content = result.content
                continue
            return DriverResult(answer=result.content or "", steps=step + 1)
        return DriverResult(
            answer=last_content,
            steps=max_steps,
            truncated=True,
            note="reached max_reasoning_steps before a final answer",
        )


class ReActDriver:
    """Drives reasoning with the prompt-based ReAct fallback and strict parsing."""

    def __init__(self, llm: LLMBackend, max_retries: int = 2) -> None:
        self._llm = llm
        self._max_retries = max_retries

    async def run(
        self,
        system_prompt: str,
        user_prompt: str,
        executor: ToolExecutor,
        max_steps: int,
    ) -> DriverResult:
        tools = executor.tool_specs()
        system = f"{system_prompt}\n\n{format_instructions(tools)}"
        messages: list[Message] = [
            Message(Role.SYSTEM, content=system),
            Message(Role.USER, content=user_prompt),
        ]
        last_thought = ""
        for step in range(max_steps):
            retries = 0
            while True:
                result = await self._llm.complete(messages)
                text = result.content or ""
                messages.append(Message(Role.ASSISTANT, content=text))
                parsed = parse_react(text)
                if parsed.thought:
                    last_thought = parsed.thought

                if parsed.kind is StepKind.FINAL:
                    return DriverResult(answer=parsed.final_answer or "", steps=step + 1)

                if parsed.kind is StepKind.ACTION:
                    observation = await executor.execute(
                        parsed.action_name or "", parsed.action_input or {}
                    )
                    messages.append(
                        Message(
                            Role.USER,
                            content="Observation: " + observation_json(observation),
                        )
                    )
                    break

                retries += 1
                if retries > self._max_retries:
                    return DriverResult(
                        answer=last_thought,
                        steps=step + 1,
                        truncated=True,
                        note=(
                            "ReAct fallback exceeded the retry budget on a malformed "
                            "response; returning deterministic status only"
                        ),
                    )
                messages.append(
                    Message(
                        Role.USER,
                        content="Observation: " + corrective_observation(parsed.error or ""),
                    )
                )
        return DriverResult(
            answer=last_thought,
            steps=max_steps,
            truncated=True,
            note="reached max_reasoning_steps before a final answer",
        )
