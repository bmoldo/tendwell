# Runbook: Elevated HTTP error rate

## Summary

This runbook covers a sustained rise in the share of HTTP 5xx responses, the
signal tracked by the `error_rate` SLO. A breach means more than one percent of
requests are failing over the evaluation window.

## First checks

- Confirm the breach is real and not a single spike: look at the trend over the
  last several minutes rather than the latest sample alone.
- Identify whether errors are concentrated in one route or spread across the
  service. Concentrated errors usually point at a recent change to that path.
- Correlate the onset time with recent deploys, config changes, or dependency
  incidents.

## Common causes

- A recent deploy introduced a regression. Roll back if the error onset lines up
  with a release.
- A downstream dependency is failing or timing out, surfacing as 5xx upstream.
- Resource exhaustion (connection pools, memory, file descriptors) under load.

## Mitigation

- If a deploy is implicated, roll back to the last known-good version.
- If a dependency is implicated, fail fast or shed load to protect the rest of
  the system while the dependency recovers.
- Once stable, capture the failing requests for a postmortem.
