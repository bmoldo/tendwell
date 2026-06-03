# Launch checklist

Phase 4 is launch readiness: the permanent storefront exists, the defaults are
verified safe, and there is no internal data anywhere in the repository. The
items below are either verified in CI on every push or are operator-run actions
that touch accounts and the public record.

## Verified in the repository and CI

- [x] **README as positioning.** Leads with the AgentOps / local-first /
  audited-actions category, shows a real health report, puts the one-command
  demo first, and states the security model in brief. See `README.md`.
- [x] **Instant demo produces a real report with no model and no egress.** The
  `docker compose up` instant tier runs the synthetic source with a stub model;
  `tests/test_instant_demo.py` drives the exact `examples/demo-instant.yaml`
  config end to end with nothing injected, so CI proves the path.
- [x] **Real-model tier documented honestly.** `docker compose --profile model up`
  pulls a small model once; the one-time download cost is stated plainly in the
  README and quickstart.
- [x] **Image runs non-root.** The Dockerfile builds a non-root image (uid
  10001); the CI `docker` job builds it and asserts the runtime uid.
- [x] **Helm chart lints and templates** in CI; its default config validates as
  local-first and deploys the read-only monitoring daemon with a hardened
  security context (non-root, read-only root filesystem, all capabilities
  dropped).
- [x] **Terraform module** passes `fmt -check` and `validate` in CI.
- [x] **Documentation set complete:** quickstart, configuration reference,
  security model, bring-your-own-LLM (with the compatibility matrix),
  add-a-data-source, register-an-executor, and CONTRIBUTING with the as-is
  maintenance stance.
- [x] **Default posture unchanged.** Read-only is the default; the open core
  ships no real executor; audit cannot be disabled; the default config makes no
  off-host call. Enforced by tests and the config validators.
- [x] **No internal data.** The CI `hygiene` job fails the build on any non-ASCII
  character (so no emojis) or any internal / prior-environment name across all
  tracked source. Verified clean.
- [x] **Quality gates green:** ruff, ruff format, mypy --strict, pytest.

## Operator-run (touch accounts or the public record)

- [ ] **Claim the names** before first publish: `tendwell` on PyPI, Docker Hub,
  and npm. The GitHub repo is already public.
- [ ] **Publish** the package (`uv build && uv publish`) and the container image
  to GHCR and/or Docker Hub. CI builds and lints these artifacts; it does not
  publish them.
- [ ] **The ten-minute stranger test** on a clean machine: follow only the README
  from `git clone` to a working report, and time it. This is the adoption gate
  that only a real run proves.
- [ ] **Real-runtime LLM validation:** fill in `docs/llm-compatibility.md` by
  running the demo against Ollama, vLLM, and a LiteLLM proxy.
- [ ] **Distribution:** publish the practitioner write-up, and share the repo and
  write-up with the relevant communities and your network. The repo and the
  write-up reinforce each other.

## The write-up

The practitioner write-up - "Operating agentic systems in production: lessons
from building Tendwell" - is the content asset that points at this repository.
The README already contains the argument; the write-up makes it once, in the
operator's voice, and links here.
