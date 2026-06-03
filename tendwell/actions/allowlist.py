"""The action allowlist: the closed, operator-defined set of actions.

An action does not exist unless the operator declared it here. The
``propose_action`` tool schema is generated from this allowlist with the action
name constrained to an enum, so the model literally cannot express an action
outside it. This module also holds the deterministic argument-schema and scope
checks; it performs no execution.
"""

from __future__ import annotations

from tendwell.actions.types import ValidationCode, ValidationOutcome
from tendwell.config.models import (
    RESERVED_ACTION_SUBSTRINGS,
    ActionConfig,
    ActionParamSpec,
)
from tendwell.interfaces.llm import ToolSpec

_TYPE_LABEL = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
}


def _matches_type(spec: ActionParamSpec, value: object) -> bool:
    if spec.type == "string":
        return isinstance(value, str)
    if spec.type == "boolean":
        return isinstance(value, bool)
    if spec.type == "integer":
        # bool is a subclass of int; an integer arg must not be a bool.
        return isinstance(value, int) and not isinstance(value, bool)
    if spec.type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    return False


def _reserved(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in RESERVED_ACTION_SUBSTRINGS)


class ActionAllowlist:
    """Indexed, validated view over the declared actions."""

    def __init__(self, actions: list[ActionConfig]) -> None:
        self._actions: dict[str, ActionConfig] = {}
        for action in actions:
            if action.name in self._actions:
                raise ValueError(f"duplicate action declared: {action.name!r}")
            if _reserved(action.name):
                # Defense in depth; the config validator already rejects these.
                raise ValueError(f"reserved action name: {action.name!r}")
            self._actions[action.name] = action

    @property
    def names(self) -> list[str]:
        return list(self._actions)

    def get(self, name: str) -> ActionConfig | None:
        return self._actions.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._actions

    def validate_arguments(
        self, action: ActionConfig, parameters: dict[str, object]
    ) -> ValidationOutcome:
        """Type-check arguments against the action's declared parameter schema."""
        declared = action.parameters
        for key in parameters:
            if key not in declared:
                return ValidationOutcome(
                    ValidationCode.SCHEMA_INVALID,
                    f"unknown argument {key!r} for action {action.name!r}",
                )
        for name, spec in declared.items():
            if name not in parameters:
                if spec.required:
                    return ValidationOutcome(
                        ValidationCode.SCHEMA_INVALID,
                        f"missing required argument {name!r} for action {action.name!r}",
                    )
                continue
            if not _matches_type(spec, parameters[name]):
                return ValidationOutcome(
                    ValidationCode.SCHEMA_INVALID,
                    f"argument {name!r} must be of type {_TYPE_LABEL[spec.type]}",
                )
        return ValidationOutcome(ValidationCode.OK)

    def propose_tool_spec(self) -> ToolSpec:
        """Build the ``propose_action`` tool schema from the allowlist."""
        action_docs = []
        for name, action in self._actions.items():
            params = ", ".join(action.parameters) or "no arguments"
            scope = ", ".join(action.scope) or "no targets configured"
            action_docs.append(f"{name} (args: {params}; targets: {scope})")
        description = (
            "Propose a mutating action for human approval. This RECORDS A "
            "PROPOSAL ONLY; it executes nothing and you cannot approve or run it. "
            "A human must approve before anything happens. Available actions: "
            + "; ".join(action_docs)
        )
        parameters = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": self.names,
                    "description": "the action to propose (must be one of the listed names)",
                },
                "targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "the targets the action would touch",
                },
                "parameters": {
                    "type": "object",
                    "description": "arguments for the action, per its schema",
                },
                "reason": {
                    "type": "string",
                    "description": "why this action is warranted, grounded in the snapshot",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "if true, plan only; mutates nothing and needs no approval",
                },
            },
            "required": ["action", "targets", "reason"],
        }
        return ToolSpec(
            name="propose_action",
            description=description,
            parameters=parameters,
        )
