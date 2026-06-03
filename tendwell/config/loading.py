"""Loading and validating configuration from YAML plus the environment.

The flow is: read YAML, expand ``${VAR}`` references against the environment,
validate into the typed model, then compute any local-first egress warnings the
caller should surface at startup. Secrets themselves are never expanded into
config values that get logged; only non-secret placeholders such as endpoints
use ``${VAR}`` expansion. Actual credentials are resolved at use time from the
``*_env`` fields.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from tendwell.config.models import TendwellConfig

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class Settings(BaseSettings):
    """Process-level settings resolved from the environment.

    These bootstrap where the config file lives; everything else is in the YAML
    config itself.
    """

    model_config = SettingsConfigDict(env_prefix="TENDWELL_", extra="ignore")

    config_path: Path = Path("tendwell.yaml")


def _expand_env(value: Any) -> Any:
    """Recursively replace ``${VAR}`` in string values from the environment.

    Unknown variables are left intact so validation can report a clear error
    rather than silently substituting an empty string.
    """
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config(path: str | Path) -> TendwellConfig:
    """Load, env-expand, and validate the config at ``path``.

    Raises ``FileNotFoundError`` if the file is missing and
    ``pydantic.ValidationError`` if the contents are invalid.
    """
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"config file not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text()) or {}
    expanded = _expand_env(raw)
    return TendwellConfig.model_validate(expanded)


def egress_warnings(config: TendwellConfig) -> list[str]:
    """Return human-readable warnings for any off-host endpoints.

    The default config is local-first and returns an empty list. Each off-host
    endpoint produces one explicit warning so the operator is never silently
    opted out of the no-egress guarantee.
    """
    warnings: list[str] = []
    for component, endpoint in config.egress_targets():
        warnings.append(
            f"local-first override: '{component}' points off-host at {endpoint}; "
            "data will leave this host for that component"
        )
    return warnings
