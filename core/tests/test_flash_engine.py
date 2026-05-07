"""Tests unitaires du flash_engine.

Tests purement unitaires (pas de DB, Redis ou HTTP). Vérifient la logique
de calcul des biais, de la veracity dynamique, l'enrichissement par les
overlays (OBI + agression) et la logique d'émission conditionnelle
(transitions + heartbeat).
"""

from datetime import datetime, timedelta

import pytest

from tik_core.scoring.flash_engine import (
    FLASH_SOURCE_SCORES,
    FlashDecision,
    HEARTBEAT_INTERVAL,
    LastEmission,
    _compute_aggression_bias,
    _compute_obi_bias,
    _enrich_with_aggression,
    _enrich_with_orderbook,
    _veracity_from_concordance,
    should_emit,
)


# ----- Helpers de test -----

def _make_decision(direction: str = "long") -> FlashDecision:
    """Crée une décision flash minimale pour les tests d'enrichissement."""
    return FlashDecision(
        entity_id="BTC",
        timestamp=datetime(2026, 4, 30, 12, 0, 0),
        direction=direction,
        confidence=0.5,
        hypothesis="test hypothesis",
    )


def _make_orderbook(bid_vol: float, ask_vol: float) -> dict:
    """Carnet d'ordres synthétique : 1 niveau bid + 1 niveau ask aux volumes voulus."""
    return {
        "bids": [["50000.00", str(bid_vol)]],
        "asks": [["50001.00", str(ask_vol)]],
    }


def _make_trades(buy_qty: float, sell_qty: float) -> list[dict]:
    """Liste de 2 aggTrades : 1 buy taker (m=False), 1 sell taker (m=True)."""
    return [
        {"q": str(buy_qty), "m": False, "p": "50000", "T": 1234},
        {"q": str(sell_qty), "m": True, "p": "50000", "T": 1235},
    ]


# ----- _veracity_from_concordance -----

@pytest.mark.parametrize(
    "direction, bias, expected_veracity",
    [
        # direction long : bias positif = concordance
        ("long", 1.0, 0.95),
        ("long", 0.5, 0.90),
        ("long", 0.0, 0.85),
        ("long", -0.5, 0.78),
        ("long", -1.0, 0.70),
        # direction short : symétrique inverse
        ("short", 1.0, 0.70),
        ("short", 0.5, 0.78),
        ("short", 0.0, 0.85),
        ("short", -0.5, 0.90),
        ("short", -1.0, 0.95),
        # direction neutral : toujours 0.85 (pas d'avis tranché à confirmer)
        ("neutral", 1.0, 0.85),
        ("neutral", 0.0, 0.85),
        ("neutral", -1.0, 0.85),
    ],
)
def test_veracity_from_concordance_matrix(direction, bias, expected_veracity):
    assert _veracity_from_concordance(direction, bias) == expected_veracity


# ----- _compute_obi_bias -----

@pytest.mark.parametrize(
    "bid_vol, ask_vol, expected_bias, expected_zone",
    [
        # Forte dominance bids → bias bull fort (OBI ≥ +0.4)
        (100.0, 30.0, 1.0, "obi_strong_bid"),
        # Dominance bids légère (+0.15 ≤ OBI < +0.4)
        (60.0, 40.0, 0.5, "obi_bid"),
        # Équilibré (-0.15 < OBI < +0.15)
        (50.0, 50.0, 0.0, "obi_balanced"),
        (52.0, 48.0, 0.0, "obi_balanced"),
        # Dominance asks légère
        (40.0, 60.0, -0.5, "obi_ask"),
        # Forte dominance asks → bias bear fort (OBI ≤ -0.4)
        (30.0, 100.0, -1.0, "obi_strong_ask"),
    ],
)
def test_compute_obi_bias_main_zones(bid_vol, ask_vol, expected_bias, expected_zone):
    orderbook = _make_orderbook(bid_vol, ask_vol)
    result = _compute_obi_bias(orderbook)
    assert result is not None
    bias, zone, _obi = result
    assert bias == expected_bias
    assert zone == expected_zone


def test_compute_obi_bias_threshold_15pct():
    """OBI exactement à +0.15 = obi_bid, à +0.149 = balanced."""
    # bid 57.5 / ask 42.5 → total 100 → obi = 15/100 = 0.15
    result = _compute_obi_bias(_make_orderbook(57.5, 42.5))
    assert result is not None
    assert result[0] == 0.5
    assert result[1] == "obi_bid"


def test_compute_obi_bias_empty_book():
    assert _compute_obi_bias({"bids": [], "asks": []}) is None


def test_compute_obi_bias_missing_keys():
    assert _compute_obi_bias({}) is None
    assert _compute_obi_bias({"bids": []}) is None


def test_compute_obi_bias_invalid_qty_returns_none():
    bad = {"bids": [["50000", "not-a-number"]], "asks": [["50001", "1.0"]]}
    assert _compute_obi_bias(bad) is None


def test_compute_obi_bias_aggregates_multiple_levels():
    """Le calcul doit additionner tous les niveaux du carnet."""
    orderbook = {
        "bids": [["50000", "10"], ["49999", "10"], ["49998", "10"]],
        "asks": [["50001", "5"], ["50002", "5"]],
    }
    # bid_vol = 30, ask_vol = 10 → obi = 20/40 = 0.5 → strong_bid
    result = _compute_obi_bias(orderbook)
    assert result is not None
    assert result[0] == 1.0
    assert result[1] == "obi_strong_bid"


# ----- _compute_aggression_bias -----

@pytest.mark.parametrize(
    "buy_qty, sell_qty, expected_bias, expected_zone",
    [
        # Forte dominance buy taker (ratio ≥ 0.65)
        (70.0, 30.0, 1.0, "aggression_strong_bid"),
        # Dominance buy légère (0.55 ≤ ratio < 0.65)
        (60.0, 40.0, 0.5, "aggression_bid"),
        # Équilibré
        (50.0, 50.0, 0.0, "aggression_balanced"),
        # Dominance sell légère
        (40.0, 60.0, -0.5, "aggression_ask"),
        # Forte dominance sell taker (ratio ≤ 0.35)
        (30.0, 70.0, -1.0, "aggression_strong_ask"),
    ],
)
def test_compute_aggression_bias_main_zones(buy_qty, sell_qty, expected_bias, expected_zone):
    trades = _make_trades(buy_qty, sell_qty)
    result = _compute_aggression_bias(trades)
    assert result is not None
    bias, zone, _ratio = result
    assert bias == expected_bias
    assert zone == expected_zone


def test_compute_aggression_bias_empty_trades():
    assert _compute_aggression_bias([]) is None


def test_compute_aggression_bias_zero_volume():
    """Tous les trades à qty=0 → total=0 → None (évite division par zéro)."""
    trades = [
        {"q": "0", "m": False},
        {"q": "0", "m": True},
    ]
    assert _compute_aggression_bias(trades) is None


def test_compute_aggression_bias_skips_invalid_entries():
    """Un trade malformé est skippé, les autres sont comptés normalement."""
    trades = [
        {"q": "100", "m": False},        # buy taker valide
        {"q": "not-a-number", "m": True},  # malformé → skip
        {"foo": "bar"},                   # malformé → skip
        {"q": "50", "m": True},          # sell taker valide
    ]
    result = _compute_aggression_bias(trades)
    assert result is not None
    # buy_vol = 100, sell_vol = 50 → ratio = 100/150 ≈ 0.667 → strong_bid
    bias, zone, ratio = result
    assert bias == 1.0
    assert zone == "aggression_strong_bid"
    assert ratio == pytest.approx(100 / 150)


def test_compute_aggression_bias_buyer_maker_convention():
    """m=True signifie maker=acheteur, donc taker=vendeur agressif → sell side."""
    trades = [
        {"q": "100", "m": True},  # 100 unités côté sell taker
    ]
    result = _compute_aggression_bias(trades)
    assert result is not None
    bias, zone, ratio = result
    assert bias == -1.0
    assert zone == "aggression_strong_ask"
    assert ratio == 0.0


# ----- _enrich_with_orderbook -----

def test_enrich_with_orderbook_strong_bid():
    decision = _make_decision("long")
    orderbook = _make_orderbook(100.0, 30.0)
    bias = _enrich_with_orderbook(decision, orderbook)

    assert bias == 1.0
    assert len(decision.evidence) == 1
    assert decision.evidence[0]["source"] == "binance_orderbook"
    assert decision.evidence[0]["score"] == FLASH_SOURCE_SCORES["binance_orderbook"]
    assert "OBI=" in decision.evidence[0]["fact"]
    assert len(decision.triggers) == 1
    assert decision.triggers[0]["type"] == "orderbook_imbalance"
    assert "obi_strong_bid" in decision.triggers[0]["value"]


def test_enrich_with_orderbook_balanced_returns_zero_bias():
    decision = _make_decision("neutral")
    orderbook = _make_orderbook(50.0, 50.0)
    bias = _enrich_with_orderbook(decision, orderbook)

    assert bias == 0.0
    # Evidence et trigger sont quand même ajoutés (zone balanced documentée)
    assert len(decision.evidence) == 1
    assert len(decision.triggers) == 1


def test_enrich_with_orderbook_invalid_book_returns_none():
    decision = _make_decision()
    bias = _enrich_with_orderbook(decision, {})
    assert bias is None
    assert decision.evidence == []
    assert decision.triggers == []


# ----- _enrich_with_aggression -----

def test_enrich_with_aggression_strong_bid():
    decision = _make_decision("long")
    trades = _make_trades(70.0, 30.0)
    bias = _enrich_with_aggression(decision, trades)

    assert bias == 1.0
    assert len(decision.evidence) == 1
    assert decision.evidence[0]["source"] == "binance_aggtrades"
    assert decision.evidence[0]["score"] == FLASH_SOURCE_SCORES["binance_aggtrades"]
    assert "buy_ratio" in decision.evidence[0]["fact"]
    assert "n=2" in decision.evidence[0]["fact"]
    assert len(decision.triggers) == 1
    assert decision.triggers[0]["type"] == "trade_aggression"
    assert "aggression_strong_bid" in decision.triggers[0]["value"]


def test_enrich_with_aggression_strong_ask():
    decision = _make_decision("short")
    trades = _make_trades(20.0, 80.0)
    bias = _enrich_with_aggression(decision, trades)
    assert bias == -1.0


def test_enrich_with_aggression_empty_returns_none():
    decision = _make_decision()
    bias = _enrich_with_aggression(decision, [])
    assert bias is None
    assert decision.evidence == []
    assert decision.triggers == []


# ----- should_emit (logique d'émission conditionnelle) -----

def test_should_emit_first_signal_emits():
    """Pas d'émission précédente → on émet."""
    decision = _make_decision("long")
    assert should_emit(decision, last=None, now=datetime(2026, 4, 30, 12, 0)) is True


def test_should_emit_direction_change_emits():
    """Transition long → short → on émet."""
    decision = _make_decision("short")
    last = LastEmission(direction="long", timestamp=datetime(2026, 4, 30, 11, 55))
    now = datetime(2026, 4, 30, 12, 0)
    assert should_emit(decision, last, now) is True


def test_should_emit_neutral_to_long_emits():
    decision = _make_decision("long")
    last = LastEmission(direction="neutral", timestamp=datetime(2026, 4, 30, 11, 55))
    now = datetime(2026, 4, 30, 12, 0)
    assert should_emit(decision, last, now) is True


def test_should_emit_same_direction_recent_skips():
    """Même direction et < heartbeat → on n'émet pas."""
    decision = _make_decision("long")
    last = LastEmission(direction="long", timestamp=datetime(2026, 4, 30, 11, 50))
    now = datetime(2026, 4, 30, 12, 0)  # 10 min plus tard < 30 min
    assert should_emit(decision, last, now) is False


def test_should_emit_same_direction_after_heartbeat_emits():
    """Même direction mais ≥ heartbeat → on émet (heartbeat tick)."""
    decision = _make_decision("long")
    last = LastEmission(direction="long", timestamp=datetime(2026, 4, 30, 11, 30))
    now = datetime(2026, 4, 30, 12, 0)  # exactement 30 min après
    assert should_emit(decision, last, now) is True


def test_should_emit_heartbeat_boundary():
    """Strictement à `heartbeat` → on émet (>=)."""
    decision = _make_decision("neutral")
    last = LastEmission(direction="neutral", timestamp=datetime(2026, 4, 30, 11, 30))
    now = last.timestamp + HEARTBEAT_INTERVAL
    assert should_emit(decision, last, now) is True


def test_should_emit_custom_heartbeat():
    """Le paramètre heartbeat peut être surchargé (utile pour tests)."""
    decision = _make_decision("long")
    last = LastEmission(direction="long", timestamp=datetime(2026, 4, 30, 11, 58))
    now = datetime(2026, 4, 30, 12, 0)
    # Avec heartbeat=1min → on est à 2 min, donc on émet
    assert should_emit(decision, last, now, heartbeat=timedelta(minutes=1)) is True
    # Avec heartbeat=5min → on est à 2 min, donc on n'émet pas
    assert should_emit(decision, last, now, heartbeat=timedelta(minutes=5)) is False


# ===== Tests ADR-018 — refactor pur OSINT (flash) =====

import pytest

from tik_core.scoring.flash_engine import (
    FlashDecision,
    _derive_osint_decision_flash,
    _veracity_from_dispersion,
)


def _make_flash_decision(direction: str = "neutral") -> FlashDecision:
    """Crée une FlashDecision minimale pour tests."""
    from datetime import datetime
    return FlashDecision(
        entity_id="BTC",
        timestamp=datetime(2026, 5, 7, 12, 0, 0),
        direction=direction,
        confidence=0.0,
        hypothesis="test",
    )


class TestDeriveOsintDecisionFlash:
    """Tests de la dérivation direction + confidence depuis combined_bias OSINT (flash)."""

    @pytest.mark.parametrize(
        "combined_bias, expected_direction, expected_confidence",
        [
            (0.62, "long", 0.62),
            (1.0, "long", 1.0),
            (0.31, "long", 0.31),
            (-0.62, "short", 0.62),
            (-1.0, "short", 1.0),
            (-0.31, "short", 0.31),
            (0.0, "neutral", 0.0),
            (0.30, "neutral", 0.30),
            (-0.30, "neutral", 0.30),
            (0.15, "neutral", 0.15),
        ],
    )
    def test_default_threshold(self, combined_bias, expected_direction, expected_confidence):
        decision = _make_flash_decision()
        _derive_osint_decision_flash(decision, combined_bias)
        assert decision.direction == expected_direction
        assert decision.confidence == pytest.approx(expected_confidence, abs=0.01)

    def test_custom_threshold(self):
        decision = _make_flash_decision()
        _derive_osint_decision_flash(decision, 0.45, threshold=0.5)
        assert decision.direction == "neutral"

    def test_hypothesis_updated(self):
        decision = _make_flash_decision()
        _derive_osint_decision_flash(decision, 0.65)
        assert "long" in decision.hypothesis.lower()
        assert "BTC" in decision.hypothesis


class TestVeracityFromDispersionFlash:
    """Tests de la veracity dérivée de la dispersion (flash)."""

    @pytest.mark.parametrize(
        "dispersion, expected_veracity",
        [
            (0.0, 0.95),
            (0.19, 0.95),
            (0.2, 0.90),
            (0.39, 0.90),
            (0.4, 0.85),
            (0.59, 0.85),
            (0.6, 0.78),
            (0.79, 0.78),
            (0.8, 0.70),
            (1.0, 0.70),
        ],
    )
    def test_veracity_paliers_flash(self, dispersion, expected_veracity):
        assert _veracity_from_dispersion(dispersion) == expected_veracity
