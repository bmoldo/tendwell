# Security model

This document is written for a security reviewer evaluating Tendwell for use in
a regulated environment. It describes, precisely, what the agent can and cannot
do, where the LLM sits relative to any change, and what is enforced
deterministically rather than left to the model's behavior.

The central claim is simple and structural: **the LLM never executes anything.**
It can only propose. Between any proposal and any change to your infrastructure
sit deterministic validation, an out-of-band human approval, and a separate
non-LLM executor. The sections below explain how that separation is built and
why it holds.

## The mutation pipeline: four separated stages

Any action that could change production runs through four stages, in separate
code paths:

```
propose -> validate -> approve -> execute
```

The model participates only in the first stage. The boundaries between stages
are not advisory; they are the structure of the system.

### 1. Propose

The model has exactly one way to express intent to act: a single
`propose_action` tool. Calling it records a structured proposal and executes
nothing. There is no second tool that runs, approves, or commits anything. The
model emits a proposal -- a named action, its targets, and its arguments -- and
control leaves the model.

### 2. Validate (deterministic, before any human)

Before a human is ever involved, a deterministic validator checks the proposal
against rules the model cannot see or influence:

- Allowlist membership: the action name must be on the configured allowlist.
- Argument schema: each argument must match the declared type and required-ness.
- Target scope: every target must fall within the action's configured `scope`.
- `max_targets`: the number of targets must not exceed the configured bound.
- Rate limit: the action must be within the configured rate window.
- Circuit breaker: the breaker must not be tripped.
- Kill switch: the kill-switch file, if configured, must not be present.

A proposal that fails any of these is rejected. Rejections are logged and never
reach a human. This matters for two reasons: a human approver is only ever shown
proposals that have already passed every deterministic gate, and a model cannot
use the approval channel as a way to surface arbitrary requests to an operator.

### 3. Approve (human, out-of-band)

A validated proposal requires a human approval before it can execute. Approval
happens out-of-band, through one of two gates:

- A synchronous CLI approval gate: a prompt the operator answers at the moment.
- An asynchronous pending-approval queue: proposals wait for an operator to act.

In both cases the approver's identity and the timestamp are captured. The model
has no tool, no endpoint, and no path to approve a proposal -- approval is
structurally outside the model's reach. A rejection or a timeout means no
execution: the default is that nothing happens.

### 4. Execute (deterministic, non-LLM)

Only after a human approval does a separate executor act. The executor is not
the model and contains no model in its path. It acts per target, using
write-scoped credentials that are held only for that run and released afterward.

Partial failure is a first-class outcome. The executor reports per-target
results, so a state like "2 of 3 succeeded" is representable and recorded
accurately rather than collapsed into a single pass/fail. There are no silent
retries on non-idempotent operations: an operation declared non-idempotent is
not transparently re-run on failure. A dry-run produces a plan, mutates nothing,
and needs no approval -- it is a safe way to see exactly what an approved run
would do.

## The LLM-never-executes invariant

Stated plainly: there is no code path by which the model causes a mutation
directly. Its only outward action is to record a proposal. Everything after that
is deterministic validation, human approval, and a separate executor. The model
cannot validate its own proposal, cannot approve it, and cannot execute it,
because it has no tool or endpoint for any of those steps. The separation is
enforced by the code structure, not by instructing the model to behave.

## Audit: append-only, hash-chained, attempted vs completed

Every stage of the lifecycle is recorded in an audit log with the following
properties:

- **Append-only.** Events are added, never edited in place.
- **Hash-chained.** Each event carries the hash of the prior event. Removing or
  altering any entry breaks the chain from that point forward, so tampering is
  detectable rather than silent.
- **Cannot be disabled.** Setting `audit.enabled: false` is rejected. There is
  no supported configuration in which actions run without an audit trail.
- **Full lifecycle.** The log records proposals, validation outcomes, approval
  decisions with identity and time, and execution results per target. This makes
  the distinction between **what was attempted** and **what actually completed**
  unambiguous -- including partial outcomes.
- **No secrets.** Credentials and secret values are never written to the audit
  log.

The reserved-name rule reinforces this: action names containing `audit`,
`approval`, `approve`, `config`, `allowlist`, `credential`, or `secret` are
rejected, so the audit log, the approval gate, the configuration, the allowlist,
and the credentials cannot themselves be the target of a proposed action.

## Escalation containment

The design deliberately limits how far any single action, or any chain of
actions, can go:

- **A single mutation path.** All changes go through the one
  propose -> validate -> approve -> execute pipeline. There is no side door.
- **No auto-chaining.** One action's result cannot trigger another action. The
  model cannot assemble a cascade; each action is its own proposal, its own
  validation, and its own approval.
- **Rate limit.** A configurable cap on actions per time window bounds the blast
  radius even within an approved session.
- **Circuit breaker.** Repeated failures trip the breaker and stop further
  execution, so a misbehaving target does not absorb repeated attempts.
- **Kill switch.** The presence of a configured kill-switch file halts all
  executions, both pending and future. It is an immediate, file-based stop that
  does not depend on the model or the agent cooperating.

## Bring-your-own executor

The open core ships **no real executor.** It includes only a test fake used in
the test suite. The practical consequence is the strongest guarantee in this
document: with no executor wired in and no action surface configured, the agent
is structurally unable to mutate anything. It can read, reason, and report, and
that is all it can do.

To enable real actions, an operator both configures an action surface and
registers their own executor. This is a deliberate, explicit step. Until it is
taken, "the agent might change something" is not a risk that exists, because
there is nothing for an approved action to call.

## Credential handling

Credentials follow least privilege and are kept out of every place they could
leak:

- **Write-scoped and short-lived.** The executor holds write-scoped credentials
  only for the duration of a run, then releases them.
- **Injected, never inline.** Credentials are supplied via environment variables
  or a secret manager and referenced by name in the config. They are never
  written into the YAML.
- **Never logged.** Secrets are never written to the audit log or other output.
- **The read path cannot mutate.** The credentials used for observing signals
  are separate from any write path; reading cannot become writing.

## Summary for a reviewer

- The LLM can only propose; it cannot validate, approve, or execute.
- Deterministic checks run before any human sees a proposal.
- Human approval is out-of-band, identity- and time-stamped, and outside the
  model's reach; the default on rejection or timeout is no execution.
- Execution is a separate, non-LLM path with per-target results and no silent
  retries on non-idempotent operations.
- The audit log is append-only, hash-chained, always on, secret-free, and makes
  attempted-vs-completed unambiguous.
- Escalation is contained by a single mutation path, no auto-chaining, a rate
  limit, a circuit breaker, and a kill switch.
- The open core ships no real executor, so an unconfigured deployment cannot
  mutate anything at all.
