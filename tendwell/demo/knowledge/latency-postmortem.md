# Postmortem: p99 latency regression

## Summary

The `latency_p99` SLO measures the 99th-percentile request duration. This
postmortem records a past incident where p99 latency rose well above the
half-second objective while median latency stayed normal, a classic tail-latency
problem affecting a fraction of requests.

## What happened

A change increased the work done on a slow code path that only a minority of
requests take. Median latency barely moved, so dashboards keyed on averages
looked healthy, but the p99 SLO breached because the tail got much worse.

## Contributing factors

- Tail latency is invisible to mean-based monitoring; only percentile SLOs
  caught it.
- The slow path was under-tested under realistic concurrency.
- A shared resource (a connection pool) saturated under the added load,
  amplifying the tail.

## Lessons

- Alert on percentile SLOs, not averages, for user-facing latency.
- When p99 rises but the median does not, suspect a slow path taken by a subset
  of requests, or contention on a shared resource, rather than a uniform
  slowdown.
- Load-test slow paths at realistic concurrency before release.
