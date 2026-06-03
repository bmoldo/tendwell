"""ConsoleOutputSink: render findings to stdout for CLI and on-demand use.

A plain-text, read-only sink. It serves findings; it has no action surface.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from tendwell.interfaces.output import Finding, OutputSink


class ConsoleOutputSink(OutputSink):
    """Writes findings as readable plain text to a stream (stdout by default)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    async def emit(self, findings: Sequence[Finding]) -> None:
        self._stream.write(self._render(findings))
        self._stream.flush()

    def _render(self, findings: Sequence[Finding]) -> str:
        lines: list[str] = []
        for finding in findings:
            lines.append(f"[{finding.severity.upper()}] {finding.title}")
            lines.append(finding.summary)
            if finding.id == "overall":
                lines.extend(self._render_overall(finding))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _render_overall(self, finding: Finding) -> list[str]:
        lines: list[str] = []
        slos = finding.evidence.get("slos")
        if isinstance(slos, list) and slos:
            lines.append("SLOs:")
            for slo in slos:
                observed = slo.get("observed_value")
                observed_text = "n/a" if observed is None else f"{observed:g}"
                lines.append(
                    f"  - {slo['name']} [{slo['state']}]: {slo['metric']}="
                    f"{observed_text}, healthy {slo['direction']} {slo['threshold']:g}"
                )
        citations = finding.evidence.get("citations")
        if isinstance(citations, list) and citations:
            lines.append("Citations:")
            for citation in citations:
                lines.append(f"  - {citation['source']} (score {citation['score']})")
        if finding.evidence.get("truncated"):
            note = finding.evidence.get("truncation_note") or "reasoning truncated"
            lines.append(f"Note: {note}")
        return lines
