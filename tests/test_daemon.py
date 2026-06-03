"""Daemon mode: a single monitoring iteration runs and exits cleanly."""

from __future__ import annotations

import pytest

from tendwell.__main__ import main


def test_daemon_once_runs_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    # --once runs a single analysis against the instant config (no model, no
    # network) and returns 0. This is the long-running command the chart deploys,
    # exercised deterministically.
    code = main(["daemon", "--config", "examples/demo-instant.yaml", "--once"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Production health" in out


def test_daemon_missing_config_returns_error() -> None:
    assert main(["daemon", "--config", "nope.yaml", "--once"]) == 2
