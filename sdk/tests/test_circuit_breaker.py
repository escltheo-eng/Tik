"""Tests du circuit breaker LOCAL.

Source de temps mockée via `time_fn` pour des tests déterministes (pas de
`asyncio.sleep` ni de freezegun).
"""

import pytest

from tik_sdk.circuit_breaker import (
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_RESET_TIMEOUT_S,
    CircuitBreaker,
)


class FakeClock:
    """Source de temps avancable manuellement."""

    def __init__(self) -> None:
        self.now: float = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _new_breaker(
    *,
    threshold: int = 3,
    reset: float = 30.0,
    clock: FakeClock | None = None,
) -> tuple[CircuitBreaker, FakeClock]:
    clock = clock or FakeClock()
    cb = CircuitBreaker(
        failure_threshold=threshold,
        reset_timeout_s=reset,
        time_fn=clock,
    )
    return cb, clock


# ----- Constructeur -----


def test_constructor_defaults() -> None:
    cb = CircuitBreaker()
    assert cb.state == "closed"
    assert cb.consecutive_failures == 0


def test_constructor_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(failure_threshold=0)
    with pytest.raises(ValueError):
        CircuitBreaker(failure_threshold=-1)


def test_constructor_rejects_invalid_reset() -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(reset_timeout_s=0)
    with pytest.raises(ValueError):
        CircuitBreaker(reset_timeout_s=-5)


def test_default_values_exposed() -> None:
    assert DEFAULT_FAILURE_THRESHOLD >= 1
    assert DEFAULT_RESET_TIMEOUT_S > 0


# ----- État closed -----


def test_can_attempt_when_closed() -> None:
    cb, _ = _new_breaker()
    assert cb.can_attempt() is True


def test_record_success_keeps_closed() -> None:
    cb, _ = _new_breaker()
    cb.record_success()
    assert cb.state == "closed"
    assert cb.consecutive_failures == 0


def test_failures_below_threshold_stay_closed() -> None:
    cb, _ = _new_breaker(threshold=3)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "closed"
    assert cb.consecutive_failures == 2


# ----- Transition closed → open -----


def test_threshold_reached_transitions_to_open() -> None:
    cb, _ = _new_breaker(threshold=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    assert cb.can_attempt() is False


def test_success_resets_failure_count() -> None:
    cb, _ = _new_breaker(threshold=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.consecutive_failures == 0
    # Encore 3 échecs nécessaires pour ouvrir
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "closed"


# ----- Transition open → half_open -----


def test_open_does_not_close_before_reset_timeout() -> None:
    cb, clock = _new_breaker(threshold=2, reset=30.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"

    clock.advance(15.0)
    assert cb.state == "open"
    assert cb.can_attempt() is False


def test_open_transitions_to_half_open_after_reset_timeout() -> None:
    cb, clock = _new_breaker(threshold=2, reset=30.0)
    cb.record_failure()
    cb.record_failure()

    clock.advance(30.0)
    assert cb.state == "half_open"
    assert cb.can_attempt() is True


def test_open_transitions_to_half_open_after_well_past_timeout() -> None:
    cb, clock = _new_breaker(threshold=2, reset=30.0)
    cb.record_failure()
    cb.record_failure()

    clock.advance(120.0)
    assert cb.state == "half_open"


# ----- Transitions depuis half_open -----


def test_half_open_success_returns_to_closed() -> None:
    cb, clock = _new_breaker(threshold=2, reset=30.0)
    cb.record_failure()
    cb.record_failure()
    clock.advance(30.0)
    assert cb.state == "half_open"

    cb.record_success()
    assert cb.state == "closed"
    assert cb.consecutive_failures == 0


def test_half_open_failure_reopens_and_resets_timer() -> None:
    cb, clock = _new_breaker(threshold=2, reset=30.0)
    cb.record_failure()
    cb.record_failure()
    clock.advance(30.0)
    # Probe en half_open échoue
    cb.record_failure()
    assert cb.state == "open"

    # Le timer a redémarré : on doit attendre encore reset
    clock.advance(15.0)
    assert cb.state == "open"
    clock.advance(15.0)  # +30 s total après reopen
    assert cb.state == "half_open"


# ----- Comportement après plusieurs cycles -----


def test_recovery_full_cycle() -> None:
    """Cycle complet : closed → open → half_open → closed → open → half_open → closed."""
    cb, clock = _new_breaker(threshold=2, reset=10.0)

    # Cycle 1 : ouvre puis se rétablit
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    clock.advance(10.0)
    assert cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed"

    # Cycle 2 : re-ouvre puis se rétablit
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    clock.advance(10.0)
    assert cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed"


def test_consecutive_failures_resets_on_success_only() -> None:
    cb, _ = _new_breaker(threshold=10)
    for _ in range(5):
        cb.record_failure()
    assert cb.consecutive_failures == 5
    cb.record_success()
    assert cb.consecutive_failures == 0
