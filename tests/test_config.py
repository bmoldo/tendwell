"""Config model and loading tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tendwell.config import (
    TendwellConfig,
    egress_warnings,
    load_config,
)
from tendwell.config.loading import _expand_env

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_CONFIG = REPO_ROOT / "tendwell.example.yaml"


def test_defaults_are_local_first() -> None:
    config = TendwellConfig()
    assert config.permissions.mode == "read_only"
    assert config.egress_targets() == []
    assert egress_warnings(config) == []


def test_example_config_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMETHEUS_URL", "http://localhost:9090")
    config = load_config(EXAMPLE_CONFIG)
    assert config.permissions.mode == "read_only"
    assert config.server.host == "127.0.0.1"
    assert [s.name for s in config.data_sources] == ["metrics"]
    # localhost endpoints only -> still local-first
    assert egress_warnings(config) == []


def test_remote_endpoint_is_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMETHEUS_URL", "http://metrics.example.com:9090")
    config = load_config(EXAMPLE_CONFIG)
    warnings = egress_warnings(config)
    assert len(warnings) == 1
    assert "data_source:metrics" in warnings[0]


def test_remote_llm_is_flagged() -> None:
    config = TendwellConfig.model_validate(
        {"llm": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o"}}
    )
    targets = dict(config.egress_targets())
    assert "llm" in targets


def test_audit_cannot_be_disabled() -> None:
    with pytest.raises(ValidationError) as excinfo:
        TendwellConfig.model_validate({"permissions": {"audit": {"enabled": False}}})
    assert "audit logging cannot be disabled" in str(excinfo.value)


def test_unknown_top_level_key_rejected() -> None:
    with pytest.raises(ValidationError):
        TendwellConfig.model_validate({"not_a_real_section": True})


def test_adapter_specific_keys_preserved() -> None:
    config = TendwellConfig.model_validate(
        {"data_sources": [{"name": "cloud", "type": "cloudwatch", "region": "eu-west-1"}]}
    )
    source = config.data_sources[0]
    # Adapter-specific keys survive on the open data-source model.
    assert source.region == "eu-west-1"


def test_env_expansion_leaves_unknown_intact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOES_NOT_EXIST", raising=False)
    assert _expand_env("${DOES_NOT_EXIST}") == "${DOES_NOT_EXIST}"
    monkeypatch.setenv("KNOWN", "value")
    assert _expand_env("${KNOWN}") == "value"
    assert _expand_env({"a": ["${KNOWN}"]}) == {"a": ["value"]}


def test_missing_config_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_config(REPO_ROOT / "nope.yaml")
