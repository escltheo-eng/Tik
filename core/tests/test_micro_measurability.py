"""Tests de la mesurabilité de l'horizon micro (fusion ADR-030, Étape 4).

Avant ces changements, l'horizon 'micro' était invisible pour toute la
machinerie de mesure : absent de HORIZON_MEASURE_HOURS (ValueError), absent
de HORIZON_SPECS_BY_SIGNAL_HORIZON (ValueError), et même une fois ajouté,
100 % des signaux micro auraient été exclus du hit rate parce qu'ils portent
TOUS circuit_breaker_status='degraded' — le marqueur shadow forcé par
/signals/ingest, PAS un flag anti-fake-news.

Couvre :
- constantes micro (fenêtre 2h alignée EXPIRY_BY_HORIZON, seuil défaut)
- filter_signals_for_horizon : micro 'degraded' inclus, 'tripped' exclu ;
  comportement flash/swing inchangé (non-régression)
- compute_track_record : 4 paliers micro 15min/30min/1h/2h
- cohérence des specs API (TRACK_RECORD_BINANCE_PARAMS)

Aucune dépendance DB/HTTP/Redis — mêmes patterns que test_metrics_hit_rate.py.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from tik_core.api.metrics import TRACK_RECORD_BINANCE_PARAMS
from tik_core.metrics.hit_rate import (
    HORIZON_DEFAULT_THRESHOLD_PCT,
    HORIZON_MEASURE_HOURS,
    filter_signals_for_horizon,
)
from tik_core.metrics.signal_track_record import (
    HORIZON_SPECS_BY_SIGNAL_HORIZON,
    compute_track_record,
)
from tik_core.scoring.publisher import EXPIRY_BY_HORIZON

NOW = datetime(2026, 7, 2, 12, 0, 0)


def _make_signal(
    *,
    entity_id: str = "BTC",
    horizon: str = "micro",
    direction: str = "long",
    timestamp: datetime,
    circuit_breaker_status: str = "degraded",
    sig_id: str = "sig-micro-test",
):
    sig = MagicMock()
    sig.id = sig_id
    sig.entity_id = entity_id
    sig.horizon = horizon
    sig.direction = direction
    sig.timestamp = timestamp
    sig.circuit_breaker_status = circuit_breaker_status
    sig.veracity = 0.70
    return sig


# ----- Constantes micro -----


def test_micro_present_in_measure_hours_and_thresholds():
    assert "micro" in HORIZON_MEASURE_HOURS
    assert "micro" in HORIZON_DEFAULT_THRESHOLD_PCT


def test_micro_measure_window_aligned_on_publisher_expiry():
    # Même logique que flash↔1h : la fenêtre de mesure canonique doit rester
    # dans la fenêtre de validité contractuelle du signal (expiry publisher).
    expiry_hours = EXPIRY_BY_HORIZON["micro"].total_seconds() / 3600
    assert HORIZON_MEASURE_HOURS["micro"] == pytest.approx(expiry_hours)


def test_micro_track_record_spec_rows():
    spec = HORIZON_SPECS_BY_SIGNAL_HORIZON["micro"]
    labels = [r["label"] for r in spec["rows"]]
    assert labels == ["15min", "30min", "1h", "2h"]
    # Le dernier palier == fenêtre contractuelle (comme flash → 1h).
    assert spec["rows"][-1]["hours"] == HORIZON_MEASURE_HOURS["micro"]
    # Paliers croissants en durée ET en seuil (bruit ↑ avec l'horizon).
    hours = [r["hours"] for r in spec["rows"]]
    thresholds = [r["threshold_pct"] for r in spec["rows"]]
    assert hours == sorted(hours)
    assert thresholds == sorted(thresholds)


def test_micro_binance_params_present():
    assert "micro" in TRACK_RECORD_BINANCE_PARAMS
    # Paliers sub-horaires → klines 15m obligatoires (comme flash).
    assert TRACK_RECORD_BINANCE_PARAMS["micro"]["interval"] == "15m"


# ----- filter_signals_for_horizon : sémantique 'degraded' micro -----


def test_micro_degraded_signals_are_measurable():
    """Le cœur du fix : 'degraded' sur micro = marqueur shadow, pas un flag."""
    sig = _make_signal(timestamp=NOW - timedelta(hours=3))
    eligible, n_excluded = filter_signals_for_horizon(
        [sig],
        horizon="micro",
        entity_id="BTC",
        since_days=30,
        now=NOW,
        include_flagged=False,
    )
    assert eligible == [sig]
    assert n_excluded == 0


def test_micro_tripped_signals_stay_excluded():
    sig = _make_signal(
        timestamp=NOW - timedelta(hours=3), circuit_breaker_status="tripped"
    )
    eligible, n_excluded = filter_signals_for_horizon(
        [sig],
        horizon="micro",
        entity_id="BTC",
        since_days=30,
        now=NOW,
        include_flagged=False,
    )
    assert eligible == []
    assert n_excluded == 1


def test_micro_too_recent_signal_not_yet_measurable():
    # Signal d'il y a 1h : la fenêtre de mesure micro est 2h → pas mûr.
    sig = _make_signal(timestamp=NOW - timedelta(hours=1))
    eligible, _ = filter_signals_for_horizon(
        [sig],
        horizon="micro",
        entity_id="BTC",
        since_days=30,
        now=NOW,
        include_flagged=False,
    )
    assert eligible == []


def test_flash_degraded_exclusion_unchanged():
    """Non-régression : hors micro, 'degraded' reste exclu (anti fake-news)."""
    sig = _make_signal(
        horizon="flash",
        timestamp=NOW - timedelta(hours=3),
        circuit_breaker_status="degraded",
    )
    eligible, n_excluded = filter_signals_for_horizon(
        [sig],
        horizon="flash",
        entity_id="BTC",
        since_days=30,
        now=NOW,
        include_flagged=False,
    )
    assert eligible == []
    assert n_excluded == 1


# ----- compute_track_record sur un signal micro -----


def _build_history(start: datetime, n_points: int, base: float, step_pct: float):
    history = []
    price = base
    ts_ms = int(start.timestamp() * 1000)
    for _ in range(n_points):
        history.append((ts_ms, price))
        price *= 1 + step_pct / 100
        ts_ms += 15 * 60 * 1000  # klines 15m, comme l'endpoint micro
    return history


def test_compute_track_record_micro_long_correct():
    ts0 = NOW - timedelta(hours=3)
    # +0.3 %/15min → +0.6 % à 30min, +2.4 % à 2h : un long gagne à tous les paliers.
    history = _build_history(ts0 - timedelta(hours=1), 40, 50000.0, 0.3)
    rows = compute_track_record(
        signal_timestamp=ts0,
        signal_direction="long",
        signal_horizon="micro",
        entity_id="BTC",
        btc_history=history,
        gold_history=[],
        now=NOW,
    )
    assert [r["label"] for r in rows] == ["15min", "30min", "1h", "2h"]
    assert all(r["available"] for r in rows)
    assert all(r["badge"] == "correct" for r in rows)


def test_compute_track_record_micro_pending_when_fresh():
    ts0 = NOW - timedelta(minutes=20)
    history = _build_history(ts0 - timedelta(hours=1), 40, 50000.0, 0.3)
    rows = compute_track_record(
        signal_timestamp=ts0,
        signal_direction="long",
        signal_horizon="micro",
        entity_id="BTC",
        btc_history=history,
        gold_history=[],
        now=NOW,
    )
    badges = {r["label"]: r["badge"] for r in rows}
    assert badges["15min"] != "en_attente"  # 20 min > 15 min → résolu
    assert badges["1h"] == "en_attente"
    assert badges["2h"] == "en_attente"


def test_compute_track_record_unknown_horizon_still_raises():
    with pytest.raises(ValueError):
        compute_track_record(
            signal_timestamp=NOW - timedelta(hours=3),
            signal_direction="long",
            signal_horizon="scalp",
            entity_id="BTC",
            btc_history=[],
            gold_history=[],
            now=NOW,
        )
