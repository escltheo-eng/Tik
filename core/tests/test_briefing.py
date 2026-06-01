"""Tests des helpers purs du briefing Telegram (Paquet 50).

Couvre la logique déterministe (résumé prix, lecture technique, climat news,
formatage, libellés) sans réseau ni DB. Les fonctions IO (`gather_briefing_data`,
`send_briefing`) ne sont pas testées ici (intégration runtime).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tik_core.notify.briefing import (
    briefing_window_label,
    climate_from_headlines,
    format_briefing,
    summarize_price,
    technical_read,
)
from tik_core.notify.telegram import send_message


def _mk_hist(prices: list[float], base: int = 1_700_000_000_000, step_ms: int = 3_600_000):
    return [(base + i * step_ms, float(p)) for i, p in enumerate(prices)]


# ---------- summarize_price ----------


def test_summarize_price_too_short_returns_none():
    assert summarize_price([(0, 100.0)]) is None
    assert summarize_price([]) is None


def test_summarize_price_basic_and_near_low():
    # 25 points décroissants 100 → 95.2 : le dernier est le plus bas.
    prices = [100 - i * 0.2 for i in range(25)]
    s = summarize_price(_mk_hist(prices))
    assert s is not None
    assert s["now"] == pytest.approx(prices[-1])
    # p24 ≈ premier point (100) → variation négative
    assert s["chg_24h"] is not None and s["chg_24h"] < 0
    assert s["low"] == pytest.approx(min(prices))
    assert s["high"] == pytest.approx(max(prices))
    assert s["near_low"] is True


def test_summarize_price_not_near_low():
    # Descend puis remonte : le dernier point est loin du plus bas.
    s = summarize_price(_mk_hist([100.0, 95.0, 100.0]))
    assert s is not None
    assert s["near_low"] is False


# ---------- technical_read ----------


def test_technical_read_too_short_returns_none():
    assert technical_read([float(i) for i in range(40)]) is None


def test_technical_read_bearish_oversold():
    # Série strictement décroissante → prix sous EMA20/50, RSI ~0 (survente).
    closes = [float(p) for p in range(200, 0, -1)]
    t = technical_read(closes)
    assert t is not None
    assert "baissière" in t["trend"]
    assert t["rsi"] < 30
    assert "survente" in t["rsi_label"]


def test_technical_read_bullish_overbought():
    # Tendance haussière avec de vraies respirations baissières (RSI défini, élevé).
    val = 100.0
    closes: list[float] = []
    for i in range(200):
        val += -1.0 if i % 5 == 0 else 2.0  # 1 repli (-1) pour 4 hausses (+2)
        closes.append(val)
    t = technical_read(closes)
    assert t is not None
    assert "haussière" in t["trend"]
    assert t["rsi"] > 70
    assert "surachat" in t["rsi_label"]


# ---------- climate_from_headlines ----------


def test_climate_empty():
    c = climate_from_headlines([])
    assert c["tilt"] is None
    assert c["bull"] == 0 and c["bear"] == 0


def test_climate_bearish():
    hl = [{"sentiment": "bear"}] * 10 + [{"sentiment": "bull"}] * 2
    c = climate_from_headlines(hl)
    assert c["bear"] == 10 and c["bull"] == 2
    assert "baissier" in c["tilt"]


def test_climate_bullish():
    hl = [{"sentiment": "bull"}] * 9 + [{"sentiment": "bear"}] * 2
    c = climate_from_headlines(hl)
    assert "haussier" in c["tilt"]


def test_climate_mixed():
    hl = [{"sentiment": "bull"}] * 5 + [{"sentiment": "bear"}] * 5
    c = climate_from_headlines(hl)
    assert "mitigé" in c["tilt"]


# ---------- briefing_window_label ----------


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (6, "Europe"),
        (8, "Europe"),
        (13, "Amériques"),
        (15, "Amériques"),
        (20, "Asie"),
        (0, "Asie"),
    ],
)
def test_briefing_window_label(hour, expected):
    now = datetime(2026, 6, 1, hour, 0, tzinfo=UTC)
    assert expected in briefing_window_label(now)


# ---------- format_briefing (smoke) ----------


def test_format_briefing_includes_all_sections():
    text = format_briefing(
        window="🌍 Matin Europe",
        now=datetime(2026, 6, 1, 6, 0, tzinfo=UTC),
        btc={
            "now": 71000.0,
            "chg_24h": -2.9,
            "chg_span": -7.5,
            "span_h": 168,
            "low": 70900.0,
            "high": 77000.0,
            "near_low": True,
        },
        gold=None,
        tech={
            "trend": "sous EMA20 & EMA50 (tendance baissière)",
            "rsi": 28.0,
            "rsi_label": "RSI 28 (proche survente)",
        },
        climate={"bull": 7, "bear": 38, "neutral": 5, "tilt": "baissier 🔴"},
        events=[
            {
                "event_name": "Non-Farm Employment Change",
                "hours_until_str": "dans 2h00",
                "assets": ["BTC", "GOLD"],
                "when_utc": "05/06 12:30",
            }
        ],
        headlines=[{"title": "Strategy sells bitcoin", "publisher": "qz.com", "sentiment": "bear"}],
    )
    assert "Briefing Tik" in text
    assert "Non-Farm Employment Change" in text
    assert "RSI 28" in text
    assert "au plus bas" in text
    assert "baissier" in text
    assert "Strategy sells bitcoin" in text
    assert "Contexte, pas prédiction" in text


def test_format_briefing_no_events_no_gold():
    text = format_briefing(
        window="🌏 Matin Asie",
        now=datetime(2026, 6, 1, 23, 0, tzinfo=UTC),
        btc=None,
        gold=None,
        tech=None,
        climate={"bull": 0, "bear": 0, "neutral": 0, "tilt": None},
        events=[],
        headlines=[],
    )
    assert "Aucun événement HIGH" in text
    assert "donnée indisponible" in text


# ---------- telegram.send_message (short-circuit sans réseau) ----------


@pytest.mark.asyncio
async def test_send_message_no_credentials_returns_false():
    assert await send_message("", "123", "hello") is False
    assert await send_message("token", "", "hello") is False
