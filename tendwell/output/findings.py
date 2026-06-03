"""Map a ``HealthReport`` onto ``Finding`` objects for an ``OutputSink``.

The report is the agent's rich result; findings are what gets served. Citations
are carried straight from the report (which built them from retrieved chunks), so
a served finding can never reference a source the model invented.
"""

from __future__ import annotations

from tendwell.core.types import HealthReport
from tendwell.interfaces.output import Finding, Severity


def report_to_findings(report: HealthReport) -> list[Finding]:
    """One overall finding plus one per breached SLO."""
    citations = [
        {"source": c.source, "document_id": c.document_id, "score": round(c.score, 4)}
        for c in report.citations
    ]
    slos = [
        {
            "name": s.name,
            "metric": s.metric,
            "state": str(s.state),
            "observed_value": s.observed_value,
            "threshold": s.threshold,
            "direction": s.direction,
            "detail": s.detail,
        }
        for s in report.snapshot.statuses
    ]
    overall = Finding(
        id="overall",
        title="Production health",
        summary=report.summary,
        severity=report.overall,
        created_at=report.snapshot.taken_at,
        evidence={
            "slos": slos,
            "citations": citations,
            "truncated": report.truncated,
            "truncation_note": report.truncation_note,
        },
    )
    findings = [overall]
    for breach in report.snapshot.breaches:
        observed = "n/a" if breach.observed_value is None else f"{breach.observed_value:g}"
        findings.append(
            Finding(
                id=f"slo:{breach.name}",
                title=f"SLO breached: {breach.name}",
                summary=(
                    f"{breach.metric}={observed}; healthy {breach.direction} {breach.threshold:g}"
                ),
                severity=Severity.CRITICAL,
                created_at=report.snapshot.taken_at,
                slo=breach.name,
                evidence={
                    "observed_value": breach.observed_value,
                    "threshold": breach.threshold,
                    "direction": breach.direction,
                },
            )
        )
    return findings
