"""Command-line entry point.

Subcommands:

- ``validate`` loads a config file, validates it, and reports any local-first
  egress overrides.
- ``run`` performs one on-demand, read-only health analysis against the
  configured stack and serves the findings to the console.
- ``daemon`` runs continuous read-only monitoring: it analyzes and reports on an
  interval until terminated, and shuts down cleanly on SIGTERM/SIGINT. This is
  the long-running mode the container image and Helm chart deploy.

The MCP server run mode is wired up in a later phase behind the output interface.
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
    from tendwell.app import run_on_demand
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
        report, results = await run_on_demand(config, question)
        await ConsoleOutputSink().emit(report_to_findings(report))
        for result in results:
            print(
                f"\naction {result.action} [{result.state}]: {result.detail}"
                + (f" (approved by {result.approver})" if result.approver else "")
            )

    asyncio.run(_go())
    return 0


def _cmd_daemon(path: str, once: bool) -> int:
    import contextlib
    import signal

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

    interval = max(1, config.server.interval_seconds)

    async def _go() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            # Signal handlers are unavailable on some platforms (Windows).
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop.set)

        sink = ConsoleOutputSink()
        while True:
            # Daemon monitoring is read-only: it analyzes and reports. Any action
            # proposals are surfaced in the report but never executed here;
            # execution requires human approval on a surface the daemon does not
            # drive.
            report = await run_analysis(config)
            await sink.emit(report_to_findings(report))
            if report.proposals:
                print(
                    f"\n{len(report.proposals)} action proposal(s) await human approval.",
                    file=sys.stderr,
                )
            if once or stop.is_set():
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval)
            if stop.is_set():
                break

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

    daemon = sub.add_parser("daemon", help="run continuous read-only monitoring on an interval")
    daemon.add_argument("--config", required=True, help="path to the config YAML")
    daemon.add_argument(
        "--once",
        action="store_true",
        help="run a single analysis and exit (useful for scheduled jobs and tests)",
    )

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args.config)
    if args.command == "run":
        return _cmd_run(args.config, args.question)
    if args.command == "daemon":
        return _cmd_daemon(args.config, args.once)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
