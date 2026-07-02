"""Gardes « DataFrame vide » des moteurs swing/flash (audit 2026-07-02).

Une réponse API valide mais vide (0 kline) levait IndexError sur
`df["close"].iloc[-1]` (calcul de `ref_price`) → cycle entier perdu,
rattrapé seulement par le catch-all du scheduler. Ces tests exercent le
chemin complet `analyze_*` avec le fetch mocké pour retourner un DataFrame
vide : la décision doit sortir sans crash, sans `ref_price`, et avec la
trace `technical_note=insufficient_history` dans l'advisory.
"""

import pandas as pd
import pytest

import tik_core.scoring.flash_engine as flash_engine
import tik_core.scoring.swing_engine as swing_engine


def _empty_klines() -> pd.DataFrame:
    return pd.DataFrame(
        {"open": [], "high": [], "low": [], "close": [], "volume": []},
        dtype=float,
    )


@pytest.mark.asyncio
async def test_analyze_swing_btc_survives_empty_klines(monkeypatch):
    async def _fake_fetch(*args, **kwargs):
        return _empty_klines()

    monkeypatch.setattr(swing_engine, "_fetch_binance_klines", _fake_fetch)
    decision = await swing_engine.analyze_swing_btc(redis=None)
    assert decision.entity_id == "BTC"
    assert "ref_price" not in decision.advisory
    assert decision.advisory.get("technical_note") == "insufficient_history"


@pytest.mark.asyncio
async def test_analyze_swing_gold_survives_empty_klines(monkeypatch):
    async def _fake_fetch(*args, **kwargs):
        return _empty_klines()

    monkeypatch.setattr(swing_engine, "_fetch_yahoo_klines", _fake_fetch)
    decision = await swing_engine.analyze_swing_gold(redis=None)
    assert decision.entity_id == "GOLD"
    assert "ref_price" not in decision.advisory
    assert decision.advisory.get("technical_note") == "insufficient_history"


@pytest.mark.asyncio
async def test_analyze_flash_btc_survives_empty_klines(monkeypatch):
    async def _fake_fetch(*args, **kwargs):
        return _empty_klines()

    monkeypatch.setattr(flash_engine, "_fetch_klines_1m", _fake_fetch)
    decision = await flash_engine.analyze_flash_btc(redis=None)
    assert decision.entity_id == "BTC"
    assert "ref_price" not in decision.advisory
    assert decision.advisory.get("technical_note") == "insufficient_history"


@pytest.mark.asyncio
async def test_analyze_swing_btc_short_history_keeps_ref_price(monkeypatch):
    """Historique court mais non vide : ref_price présent + note de trace."""
    df = pd.DataFrame(
        {
            "open": [100.0] * 10,
            "high": [101.0] * 10,
            "low": [99.0] * 10,
            "close": [100.5] * 10,
            "volume": [1.0] * 10,
        }
    )

    async def _fake_fetch(*args, **kwargs):
        return df

    monkeypatch.setattr(swing_engine, "_fetch_binance_klines", _fake_fetch)
    decision = await swing_engine.analyze_swing_btc(redis=None)
    assert decision.advisory.get("ref_price") == 100.5
    assert decision.advisory.get("technical_note") == "insufficient_history"
