"""Containment controls for the action surface.

These bound how much damage a runaway or flapping action loop can do, and give
an operator a single immediate stop. They are deterministic and clock-injectable
so CI can drive every branch without sleeping.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tendwell.config.models import CircuitBreakerConfig, RateLimitConfig


class KillSwitch:
    """A single operator control that halts all pending and future executions.

    Engaged either in-process (``engage``) or by the presence of a file, so an
    operator can stop everything without a config reload or a running prompt.
    """

    def __init__(self, file_path: str | Path | None = None) -> None:
        self._engaged = False
        self._file = Path(file_path) if file_path else None

    def engage(self) -> None:
        self._engaged = True

    @property
    def engaged(self) -> bool:
        if self._engaged:
            return True
        return self._file is not None and self._file.exists()


class RateLimiter:
    """A sliding-window cap on executed actions."""

    def __init__(self, config: RateLimitConfig, clock: Callable[[], float]) -> None:
        self._max = config.max_actions
        self._window = config.window_seconds
        self._clock = clock
        self._timestamps: list[float] = []

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        self._timestamps = [t for t in self._timestamps if t > cutoff]

    def allowed(self) -> bool:
        """Whether another action could run now (does not consume)."""
        now = self._clock()
        self._prune(now)
        return len(self._timestamps) < self._max

    def record(self) -> None:
        """Record that an execution happened now (consumes a slot)."""
        now = self._clock()
        self._prune(now)
        self._timestamps.append(now)


class CircuitBreaker:
    """Trips open after a run of execution failures; resets on success."""

    def __init__(self, config: CircuitBreakerConfig) -> None:
        self._threshold = config.failure_threshold
        self._consecutive_failures = 0

    @property
    def is_open(self) -> bool:
        return self._consecutive_failures >= self._threshold

    def record_success(self) -> None:
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        self._consecutive_failures += 1


class ActionGuards:
    """Bundle of the three containment controls, passed through the pipeline."""

    def __init__(
        self,
        kill_switch: KillSwitch,
        rate_limiter: RateLimiter,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        self.kill_switch = kill_switch
        self.rate_limiter = rate_limiter
        self.circuit_breaker = circuit_breaker
