# Tendwell - Phase 2 Implementation Spec

Companion to `CLAUDE.md` and `docs/phase-1-spec.md`. Phase 2 introduces the first
capability for Tendwell to change production. That single fact reorders the risk:
in Phases 0-1 the worst outcome was a wrong report; from here a defect can let a
language model touch a live system. The security model is the centerpiece and is
non-negotiable. Additional adapters are the lower-risk second half.

## Goal

Implement a safe, audited, human-gated action surface on top of the
`ActionSurface` ABC from Phase 0, and broaden coverage with more data-source
adapters and validated multi-runtime LLM support.

## Core invariant

The LLM proposes; it never executes. The model's only action-related capability
is to emit a structured proposal via a single `propose_action` tool, which
records intent and returns. Execution happens later, in a separate deterministic
(non-LLM) executor, only after a human approves. There is no code path by which
model output reaches the executor without passing through validation and human
approval.

## Pipeline

1. Propose - the agent emits a proposal through `propose_action`. Records intent.
2. Validate (deterministic, pre-human) - reject unknown action, schema-invalid
   arguments, out-of-scope targets, rate-limited, breaker-open, kill-switch,
   before a human is bothered. Rejections are logged.
3. Approve (human, out-of-band) - a validated proposal becomes pending and is
   surfaced to a human (CLI prompt or async queue). Identity and time captured.
   No tool, endpoint, or path lets the model approve. Rejection or timeout means
   no execution.
4. Execute (deterministic, non-LLM) - only an approved proposal reaches the
   executor, with write-scoped credentials acquired only for the execution.
   Per-target outcome recorded for every target.
5. Report and audit - outcome flows into the report and the audit log.

## Partial failure

Per-target outcomes; no silent retries on destructive ops (retry only when
provably idempotent and configured); a describable state on exit; attempted vs
completed recorded. Every action type supports a dry run that mutates nothing and
needs no approval.

## Escalation containment

Single mutation path; no auto-chaining; rate limit; circuit breaker; kill switch
halting all pending and future executions immediately.

## Audit

Append-only and tamper-evident via a hash chain; cannot be disabled; full
lifecycle with attempted vs completed distinguishable; secrets never logged.

## Part B - additional data-source adapters

Two to three adapters following the Prometheus pattern (normalize into the Phase
0 result types, fail gracefully to `unknown`, mocked-payload tests). Implemented:
Loki (logs) and a generic HTTP/JSON adapter.

## Part C - real-runtime LLM validation (operator-run)

Validate against Ollama, vLLM, and a LiteLLM proxy; record a compatibility
matrix in `docs/llm-compatibility.md`.

## Phase 2 gate

- LLM confined to proposing; no path to the executor without validation and human
  approval.
- Actions exist only via the operator allowlist; config/allowlist/audit/
  credentials structurally untargetable.
- Manual approval enforced; rejection and timeout yield no execution; no
  self-approval path.
- Partial failure first-class; no silent retries on destructive ops.
- Audit append-only, hash-chained, undisableable, attempted-vs-completed.
- Containment verified: single path, no auto-chaining, rate limit, breaker, kill
  switch.
- Dry-run mutates nothing and needs no approval.
- Action path covered in CI with fakes.
- 2-3 new adapters with mocked-payload tests.
- Real-runtime LLM validation operator-run; matrix recorded.
- Default posture unchanged: read-only, no actions, no egress; all action
  features opt-in, explicit, logged.
- ruff, mypy --strict, pytest, hygiene scan clean.

## The failure mode to watch for

An elegant shortcut that collapses propose and execute, or lets the tool loop
"just do it." That convenience forfeits the regulated-buyer trust the whole
project is positioned on. The separation is the product. Proposing and executing
stay in different code paths with a human and deterministic validation between
them, even where it feels like ceremony.
