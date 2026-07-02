"""Tests des fenêtres de mesure micro (ADR-030/ADR-034).

L'audit E2E 2026-07-02 a montré que le sous-système metrics ignorait
horizon='micro' (track record → 400, hit rate → 422) alors que la règle
projet impose « shadow MESURÉ ≥ 2 semaines avant enrôlement ». Ces tests
verrouillent la présence de micro dans chaque table de specs — logique pure,
aucune dépendance DB/réseau.
"""

from datetime import datetime, timedelta

from tik_core.api.metrics import TRACK_RECORD_BINANCE_PARAMS, TRACK_RECORD_YAHOO_PARAMS
from tik_core.metrics.hit_rate import (
    HORIZON_DEFAULT_THRESHOLD_PCT,
    HORIZON_MEASURE_HOURS,
    filter_signals_for_horizon,
)
from tik_core.metrics.signal_track_record import HORIZON_SPECS_BY_SIGNAL_HORIZON
from tik_core.scoring.publisher import EXPIRY_BY_HORIZON


class TestMicroSpecsPresence:
    def test_hit_rate_measure_hours(self):
        assert HORIZON_MEASURE_HOURS["micro"] == 2.0

    def test_hit_rate_default_threshold(self):
        assert HORIZON_DEFAULT_THRESHOLD_PCT["micro"] == 0.4

    def test_track_record_specs(self):
        specs = HORIZON_SPECS_BY_SIGNAL_HORIZON["micro"]
        labels = [r["label"] for r in specs["rows"]]
        assert labels == ["15min", "30min", "1h", "2h"]
        # La dernière fenêtre doit couvrir l'expiry publisher (2h).
        assert specs["rows"][-1]["hours"] == 2.0

    def test_track_record_binance_params(self):
        assert TRACK_RECORD_BINANCE_PARAMS["micro"]["interval"] == "15m"

    def test_no_micro_gold_via_yahoo(self):
        # L'ingest whiteliste BTC ; Yahoo (GOLD) ne doit PAS prétendre
        # supporter micro (fail-fast 400 côté endpoint).
        assert "micro" not in TRACK_RECORD_YAHOO_PARAMS

    def test_measure_window_matches_publisher_expiry(self):
        # Cohérence contractuelle : fenêtre de mesure == expiry du signal.
        assert EXPIRY_BY_HORIZON["micro"] == timedelta(hours=2)
        assert HORIZON_MEASURE_HOURS["micro"] == 2.0


class _Sig:
    """Signal duck-typé minimal pour filter_signals_for_horizon."""

    def __init__(self, ts, horizon="micro", entity_id="BTC", status="degraded"):
        self.timestamp = ts
        self.horizon = horizon
        self.entity_id = entity_id
        self.circuit_breaker_status = status
        self.direction = "long"


class TestFilterMicro:
    def test_filter_accepts_micro_and_respects_maturity(self):
        now = datetime(2026, 7, 2, 12, 0, 0)
        mature = _Sig(now - timedelta(hours=3))  # > 2h → mesurable
        too_young = _Sig(now - timedelta(hours=1))  # < 2h → pas encore
        eligible, _ = filter_signals_for_horizon(
            [mature, too_young],
            horizon="micro",
            entity_id="BTC",
            since_days=30,
            now=now,
            include_flagged=True,  # micro est TOUJOURS degraded (shadow)
        )
        assert eligible == [mature]

    def test_micro_always_degraded_needs_include_flagged(self):
        # Piège documenté : les micro sont degraded by-design → avec
        # include_flagged=False (défaut des endpoints), tout est exclu.
        now = datetime(2026, 7, 2, 12, 0, 0)
        mature = _Sig(now - timedelta(hours=3))
        eligible, n_flagged = filter_signals_for_horizon(
            [mature],
            horizon="micro",
            entity_id="BTC",
            since_days=30,
            now=now,
            include_flagged=False,
        )
        assert eligible == []
        assert n_flagged == 1
