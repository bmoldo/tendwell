# Register an executor

The action surface gates and audits; the executor does the work. The open core
ships no real executor. With no action surface configured, the agent is
structurally unable to change anything. To let Tendwell mutate real
infrastructure, an operator must provide an executor -- by design, nothing else
can.

The LLM never reaches an executor. A proposal moves through deterministic
validation and human approval first; only then, for an approved proposal, does the
executor run. The executor is the single place that touches the monitored system.

## Implement the interface

Subclass `ActionExecutor` (`tendwell/actions/executor.py`) and implement one
method:

```python
async def execute_target(
    self, proposal: ActionProposal, target: str, *, dry_run: bool
) -> TargetOutcome:
    ...
```

It acts on one target per call and returns a `TargetOutcome` for that target.

## The safety contract

The executor must honor every point below. These are not suggestions; they are the
contract the rest of the pipeline relies on.

1. It is only ever called for an APPROVED proposal. The framework runs
   deterministic validation and obtains human approval first. The executor does
   not re-check approval; it trusts that it would not have been called otherwise.
2. It acts on ONE target per call and returns a per-target
   `TargetOutcome(target, status, detail)`, where `status` is one of
   `TargetStatus.SUCCESS`, `TargetStatus.FAILURE`, `TargetStatus.SKIPPED`, or
   `TargetStatus.PLANNED`.
3. It must NOT raise for an ordinary failure. Return a `FAILURE` outcome instead.
   The pipeline records it; partial failure ("2 of 3 succeeded") is first-class.
4. When `dry_run` is true it must mutate NOTHING and return a `PLANNED` outcome.
5. It acquires write-scoped credentials only for this execution. It must never
   hold them ambiently and never log them.
6. The framework may retry an idempotent action once. A non-idempotent operation
   must therefore not be marked `idempotent` in config.

## A minimal executor

This executor restarts a service per target by calling an infrastructure API. It
returns outcomes rather than raising, honors `dry_run`, and reads its write-scoped
credential from an environment variable only when it actually executes:

```python
import os

import httpx

from tendwell.actions.executor import ActionExecutor
from tendwell.actions.types import ActionProposal, TargetOutcome, TargetStatus


class RestartServiceExecutor(ActionExecutor):
    """Restarts one service per target via an infrastructure API."""

    def __init__(self, api_url: str, token_env: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._token_env = token_env

    async def execute_target(
        self, proposal: ActionProposal, target: str, *, dry_run: bool
    ) -> TargetOutcome:
        if dry_run:
            return TargetOutcome(
                target=target,
                status=TargetStatus.PLANNED,
                detail=f"would restart {target}",
            )
        token = os.environ.get(self._token_env)
        if not token:
            return TargetOutcome(
                target=target,
                status=TargetStatus.FAILURE,
                detail="missing write-scoped credential",
            )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._api_url}/services/{target}/restart",
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError as exc:
            return TargetOutcome(
                target=target, status=TargetStatus.FAILURE, detail=f"unreachable: {exc}"
            )
        if response.status_code != 200:
            return TargetOutcome(
                target=target,
                status=TargetStatus.FAILURE,
                detail=f"api returned status {response.status_code}",
            )
        return TargetOutcome(target=target, status=TargetStatus.SUCCESS, detail="restarted")
```

The credential is fetched only inside `execute_target`, only for a real run, and
is never logged.

## Declare the action in config

An executor only runs for actions the operator has declared. Under
`permissions.actions`, declare each action with its name, the scope of allowed
targets, a parameter schema, a target cap, and whether it is idempotent. Set
`permissions.mode: actions_enabled`, and leave `require_approval` true -- approval
is mandatory and cannot be turned off.

```yaml
permissions:
  mode: actions_enabled
  actions:
    - name: restart_service
      require_approval: true
      scope:
        - web
        - worker
      max_targets: 3
      idempotent: false
      parameters:
        graceful:
          type: boolean
          required: false
```

Mark `idempotent: true` only if the operation is genuinely safe to apply twice,
because the framework may retry an idempotent action once.

## Wire the executor in

Wiring the concrete executor instance happens where the app builds the surface.
`build_action_surface` in `tendwell/app.py` takes an `executor` argument; pass your
instance there:

```python
surface = build_action_surface(
    config,
    executor=RestartServiceExecutor(
        api_url="http://infra.internal/api",
        token_env="RESTART_API_TOKEN",
    ),
    gate=gate,
)
```

With `permissions.mode` left at the default `read_only`, or with no actions
declared, `build_action_surface` returns `None` and the agent cannot mutate
anything regardless of the executor.

## Audit is automatic

Audit logging for actions is always on and cannot be disabled. Every step --
proposal, validation, approval, and per-target outcome -- is recorded to the
append-only, hash-chained audit log. The executor does not opt in to this and
cannot opt out of it.
