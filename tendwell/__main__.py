"""Command-line entry point.

Phase 0 ships a single useful subcommand, ``validate``, which loads a config
file, validates it, and reports any local-first egress overrides. Run modes
(daemon, on_demand, mcp, cli) are wired up in later phases behind the output
interface.
"""

from __future__ import annotations

import argparse
import sys

from tendwell import __version__
from tendwell.config import egress_warnings, load_config


def _cmd_validate(path: str) -> int:
    try:
        config = load_config(path)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"invalid config: {exc}", file=sys.stderr)
        return 1

    warnings = egress_warnings(config)
    if warnings:
        print("config is valid, with local-first overrides:")
        for warning in warnings:
            print(f"  warning: {warning}")
    else:
        print("config is valid; local-first (no off-host endpoints configured)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="tendwell", description=__doc__)
    parser.add_argument("--version", action="version", version=f"tendwell {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate a config file")
    validate.add_argument("config", help="path to the config YAML")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args.config)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
