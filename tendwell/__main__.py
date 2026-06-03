"""Command-line entry point.

Two subcommands in Phase 1:

- ``validate`` loads a config file, validates it, and reports any local-first
  egress overrides.
- ``run`` performs one on-demand, read-only health analysis against the
  configured stack and serves the findings to the console.

Daemon, MCP, and CLI-script run modes are wired up in later phases behind the
output interface.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from tendwell import __version__
from tendwell.config import egress_warnings, load_config
from tendwell.config.models import TendwellConfig


def _load(path: str) -> TendwellConfig:
    config = load_config(path)
    for warning in egress_warnings(config):
        print(f"warning: {warning}", file=sys.stderr)
    return config


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


def _cmd_run(path: str, question: str | None) -> int:
    from tendwell.app import run_analysis
    from tendwell.output.console import ConsoleOutputSink
    from tendwell.output.findings import report_to_findings

    try:
        config = _load(path)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"invalid config: {exc}", file=sys.stderr)
        return 1

    async def _go() -> None:
        report = await run_analysis(config, question)
        await ConsoleOutputSink().emit(report_to_findings(report))

    asyncio.run(_go())
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="tendwell", description=__doc__)
    parser.add_argument("--version", action="version", version=f"tendwell {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate a config file")
    validate.add_argument("config", help="path to the config YAML")

    run = sub.add_parser("run", help="run one on-demand health analysis")
    run.add_argument("--config", required=True, help="path to the config YAML")
    run.add_argument(
        "-q",
        "--question",
        default=None,
        help="optional question to focus the analysis",
    )

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args.config)
    if args.command == "run":
        return _cmd_run(args.config, args.question)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
