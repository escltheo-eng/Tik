"""Tests unitaires pour metrics.signal_track_record.

Module pure logic — pas de DB, HTTP ni Redis. Tous les cas sont couverts
en fournissant des historiques de prix synthétiques.
"""

from datetime import datetime, timezone

import pytest

from tik_core.metrics.signal_track_record import (
    TRACK_RECORD_HORIZONS,
    _badge_for,
    compute_track_record,
)


# ----- Fixtures historiques synthétiques -----

def _make_history(base_ts: datetime, prices: list[float], interval_h: float = 1.0) -> list[tuple[int, float]]:
    """Construit une liste [(timestamp_ms, price)] à partir d'un point de départ."""
    base_ms = int(base_ts.replace(tzinfo=timezone.utc).timestamp() * 1000)
    step_ms = int(interval_h * 3600 * 1000)
    return [(base_ms + i * step_ms, p) for i, p in enumerate(prices)]


# Timestamp de référence : signal émis il y a 10 jours → tous les horizons sont disponibles.
_10D_AGO = datetime(2026, 4, 25, 12, 0, 0)
_NOW     = datetime(2026, 5, 5,  12, 0, 0)

# Historique BTC stable à 95 000, sauf à t0+5j où il monte à 96 900 (+2%).
# On construit 250 points horaires (un peu plus de 10j) autour de _10D_AGO.
def _btc_stable_then_up() -> list[tuple[int, float]]:
    # Utilise des valeurs STRICTEMENT au-dessus des seuils car _success_for
    # teste delta_pct > threshold_pct (strict), pas >=.
    prices = [95_000.0] * 250
    prices[1]   = 95_300.0  # +0.316% > 0.3% → correct long (threshold 0.3%)
    prices[6]   = 95_300.0  # +0.316% > 0.3%
    prices[24]  = 95_500.0  # +0.526% > 0.5% → correct long (threshold 0.5%)
    prices[120] = 96_900.0  # +2.0%   > 0.5% → correct long
    return _make_history(_10D_AGO, prices)


def _btc_stable_then_down() -> list[tuple[int, float]]:
    prices = [95_000.0] * 250
    prices[1]   = 94_700.0  # -0.316% < -0.3% → correct short, raté long
    prices[6]   = 94_700.0
    prices[24]  = 94_500.0  # -0.526% < -0.5%
    prices[120] = 93_100.0  # -2.0%
    return _make_history(_10D_AGO, prices)


# ----- Tests _badge_for -----

class TestBadgeFor:
    def test_en_attente_when_not_available(self):
        assert _badge_for(available=False, p0=95_000.0, p1=None, success=None) == "en_attente"

    def test_données_manquantes_when_p0_none(self):
        assert _badge_for(available=True, p0=None, p1=95_000.0, success=None) == "données_manquantes"

    def test_données_manquantes_when_p1_none(self):
        assert _badge_for(available=True, p0=95_000.0, p1=None, success=None) == "données_manquantes"

    def test_correct_when_success_true(self):
        assert _badge_for(available=True, p0=95_000.0, p1=96_000.0, success=True) == "correct"

    def test_raté_when_success_false(self):
        assert _badge_for(available=True, p0=95_000.0, p1=94_000.0, success=False) == "raté"

    def test_en_attente_takes_priority_over_missing_data(self):
        # Même si p0/p1/success sont None, available=False → en_attente
        assert _badge_for(available=False, p0=None, p1=None, success=None) == "en_attente"


# ----- Tests compute_track_record — structure de base -----

class TestComputeTrackRecordStructure:
    def test_returns_4_rows(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO,
            signal_direction="long",
            entity_id="BTC",
            btc_history=_btc_stable_then_up(),
            gold_history=[],
            now=_NOW,
        )
        assert len(rows) == 4

    def test_row_labels_are_1h_6h_24h_5j(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO,
            signal_direction="long",
            entity_id="BTC",
            btc_history=_btc_stable_then_up(),
            gold_history=[],
            now=_NOW,
        )
        assert [r["label"] for r in rows] == ["1h", "6h", "24h", "5j"]

    def test_target_iso_format(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO,
            signal_direction="long",
            entity_id="BTC",
            btc_history=_btc_stable_then_up(),
            gold_history=[],
            now=_NOW,
        )
        # target_iso doit se terminer par Z (UTC explicite)
        for row in rows:
            assert row["target_iso"].endswith("Z")

    def test_target_iso_values(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO,
            signal_direction="long",
            entity_id="BTC",
            btc_history=_btc_stable_then_up(),
            gold_history=[],
            now=_NOW,
        )
        assert rows[0]["target_iso"] == "2026-04-25T13:00:00Z"   # +1h
        assert rows[1]["target_iso"] == "2026-04-25T18:00:00Z"   # +6h
        assert rows[2]["target_iso"] == "2026-04-26T12:00:00Z"   # +24h
        assert rows[3]["target_iso"] == "2026-04-30T12:00:00Z"   # +5j=120h


# ----- Tests compute_track_record — disponibilité selon l'âge du signal -----

class TestComputeTrackRecordAvailability:
    def test_signal_30min_old_all_en_attente(self):
        now = datetime(2026, 5, 5, 12, 30, 0)
        ts  = datetime(2026, 5, 5, 12,  0, 0)
        rows = compute_track_record(
            signal_timestamp=ts, signal_direction="long",
            entity_id="BTC", btc_history=[], gold_history=[], now=now,
        )
        assert all(r["badge"] == "en_attente" for r in rows)
        assert all(not r["available"] for r in rows)

    def test_signal_2h_old_first_row_available(self):
        now = datetime(2026, 5, 5, 14,  0, 0)
        ts  = datetime(2026, 5, 5, 12,  0, 0)
        rows = compute_track_record(
            signal_timestamp=ts, signal_direction="long",
            entity_id="BTC", btc_history=[], gold_history=[], now=now,
        )
        assert rows[0]["available"] is True    # 1h → disponible
        assert rows[1]["available"] is False   # 6h → pas encore
        assert rows[2]["available"] is False
        assert rows[3]["available"] is False

    def test_signal_7h_old_first_two_rows_available(self):
        now = datetime(2026, 5, 5, 19,  0, 0)
        ts  = datetime(2026, 5, 5, 12,  0, 0)
        rows = compute_track_record(
            signal_timestamp=ts, signal_direction="long",
            entity_id="BTC", btc_history=[], gold_history=[], now=now,
        )
        assert rows[0]["available"] is True
        assert rows[1]["available"] is True
        assert rows[2]["available"] is False
        assert rows[3]["available"] is False

    def test_signal_25h_old_three_rows_available(self):
        now = datetime(2026, 5, 6, 13,  0, 0)
        ts  = datetime(2026, 5, 5, 12,  0, 0)
        rows = compute_track_record(
            signal_timestamp=ts, signal_direction="long",
            entity_id="BTC", btc_history=[], gold_history=[], now=now,
        )
        assert rows[0]["available"] is True
        assert rows[1]["available"] is True
        assert rows[2]["available"] is True
        assert rows[3]["available"] is False

    def test_signal_10d_old_all_available(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO, signal_direction="long",
            entity_id="BTC", btc_history=_btc_stable_then_up(), gold_history=[],
            now=_NOW,
        )
        assert all(r["available"] for r in rows)


# ----- Tests compute_track_record — badges LONG -----

class TestComputeTrackRecordLong:
    def test_long_all_correct_when_price_rises(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO, signal_direction="long",
            entity_id="BTC", btc_history=_btc_stable_then_up(), gold_history=[],
            now=_NOW,
        )
        assert all(r["badge"] == "correct" for r in rows)

    def test_long_all_raté_when_price_falls(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO, signal_direction="long",
            entity_id="BTC", btc_history=_btc_stable_then_down(), gold_history=[],
            now=_NOW,
        )
        assert all(r["badge"] == "raté" for r in rows)

    def test_long_delta_pct_computed_correctly(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO, signal_direction="long",
            entity_id="BTC", btc_history=_btc_stable_then_up(), gold_history=[],
            now=_NOW,
        )
        row_5j = rows[3]
        assert row_5j["p0"] == pytest.approx(95_000.0, abs=100)
        assert row_5j["p1"] == pytest.approx(96_900.0, abs=100)
        # (96900 - 95000) / 95000 * 100 ≈ 2.0%
        assert row_5j["delta_pct"] == pytest.approx(2.0, abs=0.1)


# ----- Tests compute_track_record — badges SHORT -----

class TestComputeTrackRecordShort:
    def test_short_correct_when_price_falls(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO, signal_direction="short",
            entity_id="BTC", btc_history=_btc_stable_then_down(), gold_history=[],
            now=_NOW,
        )
        assert all(r["badge"] == "correct" for r in rows)

    def test_short_raté_when_price_rises(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO, signal_direction="short",
            entity_id="BTC", btc_history=_btc_stable_then_up(), gold_history=[],
            now=_NOW,
        )
        assert all(r["badge"] == "raté" for r in rows)


# ----- Tests compute_track_record — NEUTRAL -----

class TestComputeTrackRecordNeutral:
    def test_neutral_correct_when_stable(self):
        # Prix bouge de moins de 0.3% → neutral correct sur 1h/6h
        prices = [95_000.0] * 250
        prices[1]   = 95_200.0   # +0.21% < 0.3% → correct neutral
        prices[6]   = 95_200.0
        prices[24]  = 95_200.0   # +0.21% < 0.5% → correct neutral
        prices[120] = 95_200.0
        history = _make_history(_10D_AGO, prices)
        rows = compute_track_record(
            signal_timestamp=_10D_AGO, signal_direction="neutral",
            entity_id="BTC", btc_history=history, gold_history=[],
            now=_NOW,
        )
        assert all(r["badge"] == "correct" for r in rows)

    def test_neutral_raté_when_large_move(self):
        prices = [95_000.0] * 250
        prices[1]   = 96_000.0   # +1.05% > 0.3% → raté neutral
        prices[6]   = 96_000.0
        prices[24]  = 96_000.0   # +1.05% > 0.5% → raté neutral
        prices[120] = 96_000.0
        history = _make_history(_10D_AGO, prices)
        rows = compute_track_record(
            signal_timestamp=_10D_AGO, signal_direction="neutral",
            entity_id="BTC", btc_history=history, gold_history=[],
            now=_NOW,
        )
        assert all(r["badge"] == "raté" for r in rows)


# ----- Tests compute_track_record — cas limites -----

class TestComputeTrackRecordEdgeCases:
    def test_unknown_entity_all_données_manquantes_when_available(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO, signal_direction="long",
            entity_id="OIL", btc_history=[], gold_history=[],
            now=_NOW,
        )
        # Tous les horizons sont disponibles (signal vieux) mais pas d'historique
        assert all(r["available"] for r in rows)
        assert all(r["badge"] == "données_manquantes" for r in rows)
        assert all(r["p0"] is None for r in rows)

    def test_aware_timestamp_handled_correctly(self):
        ts_aware = _10D_AGO.replace(tzinfo=timezone.utc)
        rows = compute_track_record(
            signal_timestamp=ts_aware, signal_direction="long",
            entity_id="BTC", btc_history=_btc_stable_then_up(), gold_history=[],
            now=_NOW,
        )
        assert len(rows) == 4
        assert all(r["available"] for r in rows)

    def test_p0_exposed_even_when_future_horizon(self):
        # Signal émis il y a 30 min : p0 doit être récupéré même si aucun p1 disponible.
        now = datetime(2026, 5, 5, 12, 30, 0)
        ts  = datetime(2026, 5, 5, 12,  0, 0)
        prices = [95_000.0] * 10
        history = _make_history(ts, prices)
        rows = compute_track_record(
            signal_timestamp=ts, signal_direction="long",
            entity_id="BTC", btc_history=history, gold_history=[],
            now=now,
        )
        # Horizons pas encore disponibles mais p0 quand même récupéré
        assert rows[0]["p0"] == pytest.approx(95_000.0, abs=10)
        assert rows[0]["p1"] is None
        assert rows[0]["badge"] == "en_attente"

    def test_success_none_when_data_missing(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO, signal_direction="long",
            entity_id="BTC", btc_history=[], gold_history=[],
            now=_NOW,
        )
        assert all(r["success"] is None for r in rows)
        assert all(r["delta_pct"] is None for r in rows)

    def test_thresholds_in_rows(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO, signal_direction="long",
            entity_id="BTC", btc_history=_btc_stable_then_up(), gold_history=[],
            now=_NOW,
        )
        assert rows[0]["threshold_pct"] == 0.3   # 1h
        assert rows[1]["threshold_pct"] == 0.3   # 6h
        assert rows[2]["threshold_pct"] == 0.5   # 24h
        assert rows[3]["threshold_pct"] == 0.5   # 5j

    def test_measure_hours_in_rows(self):
        rows = compute_track_record(
            signal_timestamp=_10D_AGO, signal_direction="long",
            entity_id="BTC", btc_history=_btc_stable_then_up(), gold_history=[],
            now=_NOW,
        )
        assert [r["measure_hours"] for r in rows] == [1.0, 6.0, 24.0, 120.0]

    def test_gold_entity_uses_gold_history(self):
        gold_prices = [3_200.0] * 250
        gold_prices[120] = 3_264.0  # +2% à t0+5j
        gold_history = _make_history(_10D_AGO, gold_prices)
        rows = compute_track_record(
            signal_timestamp=_10D_AGO, signal_direction="long",
            entity_id="GOLD", btc_history=[], gold_history=gold_history,
            now=_NOW,
        )
        row_5j = rows[3]
        assert row_5j["p0"] == pytest.approx(3_200.0, abs=10)
        assert row_5j["badge"] == "correct"
