# Tendwell - Phase 3 Implementation Spec

Companion to `CLAUDE.md`, `docs/phase-1-spec.md`, and `docs/phase-2-spec.md`.
Phase 3 is the first adoption-facing phase. Phases 0-2 built a sound thing; Phase
3 builds the on-ramp that turns a stranger's GitHub visit into a person who ran
Tendwell and remembers the name. Because the project exists as a reputation flag,
this on-ramp is not secondary work - it is the work that makes all the prior work
count.

Packaging and narrative are co-equal here and interdependent: the narrative
promises "try it in minutes," and only the packaging makes that promise true.
Build them together, not in sequence.

## Goal

A stranger goes from zero to a working Tendwell in under ten minutes using only
the README, and within thirty seconds of landing on the repo understands what it
is and who it is for.

Phase 3 deliverables:

A. Packaging: `docker compose` demo, published package and container image, Helm
   chart, Terraform module.
B. Narrative and docs: README as positioning, quickstart, configuration
   reference, security-model doc, bring-your-own-LLM guide, extension guides,
   contribution and expectation-setting.

Out of scope (Phase 4 - launch): the practitioner write-up, distribution, and the
public announcement campaign. Phase 3 produces the permanent storefront; Phase 4
runs the campaign that points at it.

## The unchanged default posture

Every packaged artifact ships local-first, read-only, zero-egress by default. The
demo uses the synthetic source and the `FakeActionExecutor`; no packaged default
reaches a real model, real infrastructure, or a real executor without the
operator explicitly configuring it. Containers run as non-root. No secrets in any
image, chart, module, or example.

## Part A - Packaging

### A.1 docker compose demo (the five-minute on-ramp)

Two tiers, so the first experience is instant and the second is real:

- Instant tier: `docker compose up` brings up Tendwell against the synthetic
  source with the fake LLM, producing a real `HealthReport` immediately, no model
  download. "See it work in under a minute."
- Real tier: a compose profile that adds an Ollama service and pulls a small model
  (1-3B class) for genuine model-driven output. Document the one-time model
  download honestly; do not pretend a multi-GB pull is instant.

Both tiers are local-first with zero egress warnings. The compose file is what the
quickstart points at; they are written together and stay in lockstep.

### A.2 Published package and image (operator-run publish)

- Finalize `pyproject.toml` for distribution; `pip install tendwell` must work
  once published.
- Container image published to a registry (GHCR and/or Docker Hub), multi-arch if
  feasible, non-root, minimal base.
- Publishing is operator-run: it touches PyPI, registry, and npm accounts and the
  public record. CI builds and lints the artifacts; the publish step and the
  prerequisite name claims are operator actions. Claim the names before first
  publish.
- Pin dependencies; SBOM and release signing are stretch, not gating.

### A.3 Helm chart

- Chart deploying Tendwell on Kubernetes, values for config and secret references
  (never inline secrets). Secure defaults mirroring local-first, read-only.
- `helm lint` and a template-render check in CI. Real cluster install is
  operator-run.

### A.4 Terraform module

- Module to provision a Tendwell deployment. `terraform validate` and `fmt -check`
  in CI. Real apply is operator-run.

## Part B - Narrative and docs

### B.1 README as positioning (the storefront and the flag)

Two jobs at once: convert a visitor into someone who runs it, and plant the
reputation flag.

- First screen, thirty-second comprehension: what Tendwell is (an agentic,
  self-hosted, local-first production-health monitor with audited, human-gated
  actions), who it is for (teams in security-conscious and regulated
  environments), and why it is different. Lead with category vocabulary -
  AgentOps, local-first, audited actions.
- Show, do not just tell: an example `HealthReport` (the actual output).
- The quickstart up top: the instant `docker compose up` path, copy-pasteable.
- Security model in brief: propose / human-gate / deterministic-execute /
  hash-chained audit, and the "no real executor in the open core - mutation is
  opt-in and BYO" guarantee. For the regulated reader this paragraph is the pitch.
- Local-first guarantee stated plainly.
- Links: full docs, contributing, license.

Positioning prose, not a feature dump. No emojis.

### B.2 Quickstart

Zero to a working Tendwell in under ten minutes, validated against the actual
compose demo. Instant tier first, then the real-model tier, then "point it at your
own Prometheus." Each step copy-pasteable and tested.

### B.3 Configuration reference

Complete reference for the config surface: every field, defaults, and which values
are locked (read-only default, undisableable audit, local-first default) with the
rationale. Keep `tendwell.example.yaml` annotated and in sync.

### B.4 Security model doc

The full version of the README's brief: the propose/validate/approve/execute
separation, the LLM-never-executes invariant, partial-failure handling, the
hash-chained append-only audit and attempted-vs-completed, escalation containment,
and the BYO-executor design. Written for a security reviewer at a regulated buyer.

### B.5 Bring-your-own-LLM guide

How to point Tendwell at any OpenAI-compatible runtime, the `native_tool_calling`
flag and when the ReAct fallback engages, and the compatibility matrix from Phase
2 Part C.

### B.6 Extension guides

- Add a data source: implement the `DataSource` interface, with Prometheus/Loki/
  HTTP as worked examples.
- Register an executor: how an operator wires a real executor, with the safety
  contract spelled out (framework gates and audits; executor does the work;
  approval required). Essential because the open core ships none.

### B.7 Contribution and expectation-setting

- `CONTRIBUTING.md` and issue/PR templates.
- Set maintenance expectations explicitly: provided as-is, PRs welcome, no support
  SLA. Time-protection discipline: the project is a reputation asset, not an
  obligation that competes with billable hours.

## Build order within Phase 3

Narrative and packaging interleave; do not finish one before starting the other.

1. README skeleton with the positioning and first-screen comprehension.
2. docker compose instant tier (fake LLM, synthetic source).
3. Quickstart instant path, validated against the compose.
4. docker compose real tier (Ollama + small model profile); extend quickstart.
5. Package and image build wired in CI (publish operator-run; names claimed first).
6. Helm chart (+ `helm lint`/template check in CI).
7. Terraform module (+ `validate`/`fmt` in CI).
8. Reference docs: configuration reference, security model, BYO-LLM (+ matrix),
   add-a-source, register-an-executor.
9. CONTRIBUTING, templates, expectation-setting.
10. Operator-run: the under-ten-minutes stranger test on a clean machine, and the
    publish.

Each step lands clean (ruff/mypy/pytest, hygiene, no emojis, plain commits). Docs
are part of the hygiene scan too - ASCII only.

## Phase 3 gate (all must hold)

- [ ] `docker compose up` instant tier produces a real `HealthReport` with no model
      download and zero egress warnings.
- [ ] Real-model compose profile produces genuine model-driven output; the download
      cost is documented honestly.
- [ ] A stranger reaches a working Tendwell in under ten minutes using only the
      README (operator-verified on a clean machine).
- [ ] Thirty-second comprehension: the README's first screen conveys what it is,
      who it is for, and why it differs.
- [ ] Package builds and `pip install tendwell` works from the built artifact;
      image runs non-root; names claimed and publish ready (publish operator-run).
- [ ] Helm chart lints and templates in CI; Terraform module validates in CI.
- [ ] Docs set complete: quickstart, config reference, security model, BYO-LLM +
      matrix, add-a-source, register-an-executor, CONTRIBUTING with
      expectation-setting.
- [ ] Every packaged default is local-first, read-only, no real executor, no
      secrets, non-root.
- [ ] ruff, mypy --strict, pytest, hygiene scan all clean. No emojis. Plain commits.

## A note for review

The failure mode in an adoption phase is making the packaging excellent and the
narrative an afterthought - a flawless Helm chart under a README that opens with an
architecture diagram and a dependency list. For this project that is backwards.
The README's first screen does more for the goal than any chart, because the goal
is reputation and the README is where a stranger decides whether you are worth
remembering. Give the positioning prose the same care the security model got. The
two halves are co-equal precisely because neither works without the other.
