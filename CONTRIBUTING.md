# Contributing to Tendwell

Thank you for your interest in Tendwell. Issues and pull requests are welcome.
Please read the conventions below before you open one -- they are enforced and a
review will ask you to fix violations.

## Maintenance stance

Tendwell is provided as-is under Apache-2.0. Issues and pull requests are welcome
and read, but there is no support SLA: there is no guaranteed response time and no
commitment to triage, fix, or merge on any schedule. This is intentional
expectation-setting, not a lack of interest. Contributions that come with tests
and follow the conventions are the easiest to accept.

## Development setup

Tendwell uses Python 3.11+ and uv. Install dependencies, including dev tools:

```
uv sync --dev
```

## Quality gates

All of these must pass before a change is merged. Run them locally:

```
uv run ruff check . && uv run ruff format --check .
uv run mypy tendwell
uv run pytest
```

- `ruff` -- linting and formatting. Run `uv run ruff format .` to apply
  formatting.
- `mypy` -- runs in strict mode. Full type hints are required, not optional.
- `pytest` -- the test suite.

## Conventions

- No emojis anywhere -- not in code, comments, docs, or commit messages.
- ASCII only. Use `->` instead of arrow glyphs, `--` instead of em-dashes, and
  straight quotes.
- Commit messages are plain and imperative ("Add Loki range queries"). No AI
  attribution and no co-author trailers.
- No company, client, or internal-environment names anywhere in the repository.
  A deployment is one YAML file plus injected secrets; the code carries zero
  environment-specific values.
- Full type hints on everything. mypy strict must pass.
- Every public interface has a docstring.
- Secrets are referenced by environment variable, never inlined. Configs name the
  env var that holds a token or key; they never contain the value.

## Adding tests

New adapters need unit tests. Tests must not depend on live infrastructure:

- For HTTP-based data source adapters, use `httpx.MockTransport` with mocked
  payloads. Cover success, empty, error, and auth-failure cases.
- The demo stack enables end-to-end tests with no real infrastructure: the stub
  LLM (`llm.provider: stub`), the hash embedder (`embeddings.provider: hash`), and
  the synthetic data source run with no network. Use them to exercise the full
  pipeline deterministically.
- For executors, use the bundled `FakeActionExecutor`
  (`tendwell/actions/executor.py`) to drive the action pipeline without touching
  real infrastructure.

## Issues and pull requests

- Bug reports and feature requests use the templates under
  [.github/ISSUE_TEMPLATE](.github/ISSUE_TEMPLATE).
- Pull requests follow the
  [pull request template](.github/PULL_REQUEST_TEMPLATE.md). Confirm the checklist:
  the quality gates pass, there are no emojis, commit messages are plain, and docs
  are updated when behavior changes.
