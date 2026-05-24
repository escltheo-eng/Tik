"""Tests M4 — compute_signal_freshness (détection de panne silencieuse).

Logique pure, pas de DB/Redis/HTTP. Cf. CLAUDE.md audit 2026-05-24 M4.
"""

from datetime import datetime, timedelta

from tik_core.metrics.freshness import (
    DEFAULT_STALENESS_THRESHOLD_SECONDS,
    compute_signal_freshness,
)

NOW = datetime(2026, 5, 24, 12, 0, 0)


def test_default_threshold_is_60_min():
    assert DEFAULT_STALENESS_THRESHOLD_SECONDS == 3600


def test_no_signal_is_stale():
    fr = compute_signal_freshness(None, NOW)
    assert fr.stale is True
    assert fr.last_signal_at is None
    assert fr.age_seconds is None
    assert fr.threshold_seconds == DEFAULT_STALENESS_THRESHOLD_SECONDS


def test_recent_signal_not_stale():
    fr = compute_signal_freshness(NOW - timedelta(minutes=10), NOW)
    assert fr.stale is False
    assert fr.age_seconds == 600.0


def test_old_signal_is_stale():
    fr = compute_signal_freshness(NOW - timedelta(minutes=90), NOW)
    assert fr.stale is True
    assert fr.age_seconds == 5400.0


def test_exactly_at_threshold_not_stale():
    # age == threshold → pas stale (comparaison stricte >)
    last = NOW - timedelta(seconds=DEFAULT_STALENESS_THRESHOLD_SECONDS)
    fr = compute_signal_freshness(last, NOW)
    assert fr.age_seconds == float(DEFAULT_STALENESS_THRESHOLD_SECONDS)
    assert fr.stale is False


def test_one_second_over_threshold_is_stale():
    last = NOW - timedelta(seconds=DEFAULT_STALENESS_THRESHOLD_SECONDS + 1)
    assert compute_signal_freshness(last, NOW).stale is True


def test_clock_skew_future_signal_is_fresh():
    # last_signal_at dans le futur (clock skew) → age ramené à 0, pas stale
    fr = compute_signal_freshness(NOW + timedelta(minutes=5), NOW)
    assert fr.age_seconds == 0.0
    assert fr.stale is False


def test_custom_threshold():
    last = NOW - timedelta(minutes=45)
    assert compute_signal_freshness(last, NOW, threshold_seconds=30 * 60).stale is True
    assert compute_signal_freshness(last, NOW, threshold_seconds=60 * 60).stale is False
