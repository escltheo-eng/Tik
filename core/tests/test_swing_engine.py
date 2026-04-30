"""Tests unitaires du swing_engine.

Tests purement unitaires (pas de DB, Redis ou HTTP). Vérifient la logique
de calcul des biais, de la veracity dynamique, et l'enrichissement des
décisions par les overlays sentiment / macro.
"""

from datetime import datetime

import pytest

from tik_core.scoring.swing_engine import (
    SOURCE_SCORES,
    SwingDecision,
    _compute_cot_bias,
    _compute_cryptocompare_bias,
    _compute_dxy_bias,
    _compute_fg_bias,
    _enrich_with_cot,
    _enrich_with_cryptocompare,
    _enrich_with_dxy,
    _enrich_with_fear_greed,
    _veracity_from_concordance,
)


# ----- Helpers de test -----

def _make_decision(direction: str = "long") -> SwingDecision:
    """Crée une décision swing minimale pour les tests d'enrichissement."""
    return SwingDecision(
        entity_id="TEST",
        timestamp=datetime(2026, 4, 29, 12, 0, 0),
        direction=direction,
        confidence=0.5,
        hypothesis="test hypothesis",
    )


def _make_dxy_history(past_value: float, recent_value: float) -> list[dict]:
    """Crée un faux history FRED de 6 points (recent à idx 0, past à idx 5)."""
    mid = (past_value + recent_value) / 2
    return [
        {"value": str(recent_value)},
        {"value": str(mid)},
        {"value": str(mid)},
        {"value": str(mid)},
        {"value": str(mid)},
        {"value": str(past_value)},
    ]


# ----- _compute_fg_bias -----

@pytest.mark.parametrize(
    "value, expected_bias, expected_zone",
    [
        # Coeur des 5 zones
        (10, 1.0, "extreme_fear"),
        (35, 0.5, "fear"),
        (50, 0.0, "neutral"),
        (65, -0.5, "greed"),
        (90, -1.0, "extreme_greed"),
        # Bornes (value <= 25 = extreme_fear, etc.)
        (25, 1.0, "extreme_fear"),
        (26, 0.5, "fear"),
        (45, 0.5, "fear"),
        (46, 0.0, "neutral"),
        (55, 0.0, "neutral"),
        (56, -0.5, "greed"),
        (74, -0.5, "greed"),
        (75, -1.0, "extreme_greed"),
        # Extrêmes
        (0, 1.0, "extreme_fear"),
        (100, -1.0, "extreme_greed"),
    ],
)
def test_compute_fg_bias(value, expected_bias, expected_zone):
    bias, zone = _compute_fg_bias(value)
    assert bias == expected_bias
    assert zone == expected_zone


# ----- _compute_cryptocompare_bias -----

@pytest.mark.parametrize(
    "score, expected_bias, expected_zone",
    [
        # Coeur des 5 zones
        (0.5, 1.0, "news_strong_bullish"),
        (0.2, 0.5, "news_bullish"),
        (0.0, 0.0, "news_neutral"),
        (-0.2, -0.5, "news_bearish"),
        (-0.5, -1.0, "news_strong_bearish"),
        # Bornes
        (0.4, 1.0, "news_strong_bullish"),
        (0.39, 0.5, "news_bullish"),
        (0.1, 0.5, "news_bullish"),
        (0.09, 0.0, "news_neutral"),
        (-0.09, 0.0, "news_neutral"),
        (-0.1, -0.5, "news_bearish"),
        (-0.4, -1.0, "news_strong_bearish"),
        # Extrêmes
        (1.0, 1.0, "news_strong_bullish"),
        (-1.0, -1.0, "news_strong_bearish"),
    ],
)
def test_compute_cryptocompare_bias(score, expected_bias, expected_zone):
    bias, zone = _compute_cryptocompare_bias(score)
    assert bias == expected_bias
    assert zone == expected_zone


# ----- _compute_dxy_bias -----

@pytest.mark.parametrize(
    "past, recent, expected_bias, expected_zone",
    [
        # Forte hausse DXY (≥ +1%) → bear sur GOLD
        (100.0, 102.0, -1.0, "dxy_strong_up"),
        # Hausse légère DXY (+0.3% à +1%) → bear léger
        (100.0, 100.5, -0.5, "dxy_up"),
        # Stable
        (100.0, 100.0, 0.0, "dxy_stable"),
        (100.0, 100.2, 0.0, "dxy_stable"),
        # Baisse légère DXY → bull léger sur GOLD
        (100.0, 99.5, 0.5, "dxy_down"),
        # Forte baisse DXY → bull sur GOLD
        (100.0, 98.0, 1.0, "dxy_strong_down"),
    ],
)
def test_compute_dxy_bias_main_zones(past, recent, expected_bias, expected_zone):
    history = _make_dxy_history(past, recent)
    result = _compute_dxy_bias(history)
    assert result is not None
    bias, zone, recent_v, past_v = result
    assert bias == expected_bias
    assert zone == expected_zone
    assert recent_v == recent
    assert past_v == past


def test_compute_dxy_bias_empty_history():
    assert _compute_dxy_bias([]) is None


def test_compute_dxy_bias_too_few_values():
    # Moins de 5 valeurs valides → None
    history = [{"value": str(v)} for v in [100, 101, 102, 103]]
    assert _compute_dxy_bias(history) is None


def test_compute_dxy_bias_filters_invalid_values():
    # Les sentinelles FRED ('.', '', None) sont ignorées dans le comptage.
    history = [
        {"value": "102"},
        {"value": "."},
        {"value": ""},
        {"value": None},
        {"value": "101"},
        {"value": "100.5"},
        {"value": "100.2"},
        {"value": "100"},
    ]
    result = _compute_dxy_bias(history)
    assert result is not None
    # 5 valeurs valides : [102, 101, 100.5, 100.2, 100]
    # past_idx = min(5, 5-1) = 4 → past=100
    # variation = (102-100)/100*100 = +2% → strong_up
    assert result[0] == -1.0
    assert result[1] == "dxy_strong_up"


def test_compute_dxy_bias_zero_past_returns_none():
    # Garde-fou divisions par zéro
    history = _make_dxy_history(0.0, 1.0)
    assert _compute_dxy_bias(history) is None


# ----- _veracity_from_concordance -----

@pytest.mark.parametrize(
    "direction, bias, expected_veracity",
    [
        # direction long : bias positif = concordance, bias négatif = divergence
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
        # direction neutral : aucun avis tranché à confirmer → toujours 0.85
        ("neutral", 1.0, 0.85),
        ("neutral", 0.5, 0.85),
        ("neutral", 0.0, 0.85),
        ("neutral", -0.5, 0.85),
        ("neutral", -1.0, 0.85),
    ],
)
def test_veracity_from_concordance_matrix(direction, bias, expected_veracity):
    assert _veracity_from_concordance(direction, bias) == expected_veracity


# ----- _enrich_with_fear_greed -----

def test_enrich_with_fear_greed_valid():
    decision = _make_decision("long")
    fg = {"value": 30, "classification": "Fear"}
    bias = _enrich_with_fear_greed(decision, fg)

    assert bias == 0.5  # zone fear → bias contrarian bull
    assert len(decision.evidence) == 1
    assert decision.evidence[0]["source"] == "alternative_me_fng"
    assert decision.evidence[0]["score"] == SOURCE_SCORES["alternative_me_fng"]
    assert "FG=30" in decision.evidence[0]["fact"]
    assert "Fear" in decision.evidence[0]["fact"]
    assert len(decision.triggers) == 1
    assert decision.triggers[0]["type"] == "fear_greed"
    assert "fear" in decision.triggers[0]["value"]


def test_enrich_with_fear_greed_extreme_fear():
    decision = _make_decision("long")
    fg = {"value": 5, "classification": "Extreme Fear"}
    bias = _enrich_with_fear_greed(decision, fg)
    assert bias == 1.0  # forte concordance contrarian bull


def test_enrich_with_fear_greed_missing_value():
    decision = _make_decision()
    fg = {"classification": "Fear"}  # pas de "value"
    bias = _enrich_with_fear_greed(decision, fg)
    assert bias is None
    # La décision n'est pas modifiée
    assert decision.evidence == []
    assert decision.triggers == []


def test_enrich_with_fear_greed_invalid_value_type():
    decision = _make_decision()
    fg = {"value": "not-a-number"}
    bias = _enrich_with_fear_greed(decision, fg)
    assert bias is None
    assert decision.evidence == []


# ----- _enrich_with_cryptocompare -----

def test_enrich_with_cryptocompare_valid():
    decision = _make_decision("long")
    cc = {
        "score": 0.3,
        "n_articles": 50,
        "n_bullish": 15,
        "n_bearish": 10,
    }
    bias = _enrich_with_cryptocompare(decision, cc)

    assert bias == 0.5  # zone news_bullish
    assert len(decision.evidence) == 1
    assert decision.evidence[0]["source"] == "cryptocompare_news"
    assert decision.evidence[0]["score"] == SOURCE_SCORES["cryptocompare_news"]
    fact = decision.evidence[0]["fact"]
    assert "+0.30" in fact
    assert "bull=15" in fact
    assert "bear=10" in fact
    assert len(decision.triggers) == 1
    assert decision.triggers[0]["type"] == "news_sentiment"


def test_enrich_with_cryptocompare_strong_bearish():
    decision = _make_decision("short")
    cc = {"score": -0.6, "n_articles": 50, "n_bullish": 5, "n_bearish": 25}
    bias = _enrich_with_cryptocompare(decision, cc)
    assert bias == -1.0


def test_enrich_with_cryptocompare_missing_score():
    decision = _make_decision()
    cc = {"n_articles": 50}
    bias = _enrich_with_cryptocompare(decision, cc)
    assert bias is None
    assert decision.evidence == []
    assert decision.triggers == []


# ----- _enrich_with_dxy -----

def test_enrich_with_dxy_valid_strong_up():
    decision = _make_decision("short")
    history = _make_dxy_history(100.0, 102.0)
    bias = _enrich_with_dxy(decision, history)

    assert bias == -1.0  # DXY strong up → bear sur GOLD
    assert len(decision.evidence) == 1
    assert decision.evidence[0]["source"] == "fred_dtwexbgs"
    assert decision.evidence[0]["score"] == SOURCE_SCORES["fred_dtwexbgs"]
    assert "DXY=102.00" in decision.evidence[0]["fact"]
    assert "+2.00%" in decision.evidence[0]["fact"]
    assert len(decision.triggers) == 1
    assert decision.triggers[0]["type"] == "dxy_correlation"


def test_enrich_with_dxy_strong_down():
    decision = _make_decision("long")
    history = _make_dxy_history(100.0, 98.0)
    bias = _enrich_with_dxy(decision, history)
    assert bias == 1.0  # DXY strong down → bull sur GOLD


def test_enrich_with_dxy_empty_history():
    decision = _make_decision()
    bias = _enrich_with_dxy(decision, [])
    assert bias is None
    assert decision.evidence == []
    assert decision.triggers == []


def test_enrich_with_dxy_insufficient_history():
    decision = _make_decision()
    history = [{"value": str(v)} for v in [100, 101, 102]]  # < 5 valeurs
    bias = _enrich_with_dxy(decision, history)
    assert bias is None
    assert decision.evidence == []


# ----- _compute_cot_bias -----

@pytest.mark.parametrize(
    "net_pct, expected_bias, expected_zone",
    [
        # Coeur des 5 zones
        (0.85, -1.0, "mm_extreme_long"),
        (0.55, -0.5, "mm_net_long"),
        (0.0, 0.0, "mm_balanced"),
        (-0.55, 0.5, "mm_net_short"),
        (-0.85, 1.0, "mm_extreme_short"),
        # Bornes (>= 0.7 = extreme_long, etc.)
        (0.7, -1.0, "mm_extreme_long"),
        (0.69, -0.5, "mm_net_long"),
        (0.4, -0.5, "mm_net_long"),
        (0.39, 0.0, "mm_balanced"),
        (-0.39, 0.0, "mm_balanced"),
        (-0.4, 0.5, "mm_net_short"),
        (-0.69, 0.5, "mm_net_short"),
        (-0.7, 1.0, "mm_extreme_short"),
        # Extrêmes
        (1.0, -1.0, "mm_extreme_long"),
        (-1.0, 1.0, "mm_extreme_short"),
    ],
)
def test_compute_cot_bias(net_pct, expected_bias, expected_zone):
    bias, zone = _compute_cot_bias(net_pct)
    assert bias == expected_bias
    assert zone == expected_zone


# ----- _enrich_with_cot -----

def test_enrich_with_cot_valid_extreme_long():
    decision = _make_decision("long")
    cot = {
        "mm_long": 123681,
        "mm_short": 30705,
        "mm_net_pct": 0.602,
        "report_date": "2026-04-21T00:00:00.000",
    }
    bias = _enrich_with_cot(decision, cot)

    assert bias == -0.5  # zone mm_net_long → contrarian bear GOLD
    assert len(decision.evidence) == 1
    assert decision.evidence[0]["source"] == "cftc_cot"
    assert decision.evidence[0]["score"] == SOURCE_SCORES["cftc_cot"]
    fact = decision.evidence[0]["fact"]
    assert "long=123681" in fact
    assert "short=30705" in fact
    assert "+0.60" in fact
    assert "2026-04-21" in fact
    assert len(decision.triggers) == 1
    assert decision.triggers[0]["type"] == "cot_positioning"
    assert "mm_net_long" in decision.triggers[0]["value"]


def test_enrich_with_cot_extreme_short():
    decision = _make_decision("short")
    cot = {
        "mm_long": 10000,
        "mm_short": 90000,
        "mm_net_pct": -0.8,
        "report_date": "2026-04-21",
    }
    bias = _enrich_with_cot(decision, cot)
    assert bias == 1.0  # contrarian bull GOLD


def test_enrich_with_cot_balanced():
    decision = _make_decision("neutral")
    cot = {
        "mm_long": 50000,
        "mm_short": 50000,
        "mm_net_pct": 0.0,
        "report_date": "2026-04-21",
    }
    bias = _enrich_with_cot(decision, cot)
    assert bias == 0.0
    # Evidence et trigger sont quand même ajoutés (zone balanced documentée)
    assert len(decision.evidence) == 1
    assert len(decision.triggers) == 1


def test_enrich_with_cot_missing_field():
    decision = _make_decision()
    cot = {"mm_long": 100, "mm_short": 50}  # pas de mm_net_pct
    bias = _enrich_with_cot(decision, cot)
    assert bias is None
    assert decision.evidence == []
    assert decision.triggers == []


def test_enrich_with_cot_invalid_value_type():
    decision = _make_decision()
    cot = {
        "mm_long": "not-a-number",
        "mm_short": 50,
        "mm_net_pct": 0.0,
    }
    bias = _enrich_with_cot(decision, cot)
    assert bias is None
    assert decision.evidence == []


def test_enrich_with_cot_missing_report_date_uses_unknown():
    decision = _make_decision("long")
    cot = {"mm_long": 100, "mm_short": 50, "mm_net_pct": 0.33}  # pas de report_date
    bias = _enrich_with_cot(decision, cot)
    assert bias == 0.0  # mm_balanced
    # report_date par défaut = "unknown" → tronqué à "unknown"[:10] = "unknown"
    assert "unknown" in decision.evidence[0]["fact"]
