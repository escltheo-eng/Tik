"""Tests du TradingViewTAIngester (SHADOW, ADR-031).

Couvre :
- le helper pur `_build_item` (normalisation d'un objet Analysis) + cas dégradés ;
- `_fetch_target_sync` avec un `TA_Handler` mocké (succès, lib qui lève, None) ;
- un cycle complet avec un faux Redis (clés/TTL/history écrits, cas no_data).

Aucune dépendance réseau ni Redis réelle.
"""

import json

import pytest

from tik_core.aggregator import tradingview_ta_ingester as mod
from tik_core.aggregator.tradingview_ta_ingester import (
    MACRO_TARGETS,
    MICRO_TARGETS,
    REDIS_HISTORY_MACRO,
    REDIS_KEY_MACRO,
    REDIS_KEY_MICRO_TPL,
    TradingViewTAIngester,
    TVTarget,
    _build_item,
    _safe_float,
)

REDIS_KEY_MICRO_BTC = REDIS_KEY_MICRO_TPL.format(entity="btc")
REDIS_KEY_MICRO_GOLD = REDIS_KEY_MICRO_TPL.format(entity="gold")

T_DXY = TVTarget("DXY", "macro", "1d", (("cfd", "TVC", "DXY"),))


class FakeAnalysis:
    """Imite l'objet Analysis de tradingview-ta (attributs summary/oscillators/...)."""

    def __init__(self, summary=None, oscillators=None, moving_averages=None, indicators=None):
        self.summary = summary
        self.oscillators = oscillators
        self.moving_averages = moving_averages
        self.indicators = indicators


VALID = FakeAnalysis(
    summary={"RECOMMENDATION": "BUY", "BUY": 12, "SELL": 5, "NEUTRAL": 9},
    oscillators={"RECOMMENDATION": "NEUTRAL"},
    moving_averages={"RECOMMENDATION": "STRONG_BUY"},
    indicators={"RSI": 47.2134, "close": 104.13},
)


class TestSafeFloat:
    def test_valid(self):
        assert _safe_float("1.23456") == 1.2346  # arrondi 4 décimales

    def test_none(self):
        assert _safe_float(None) is None

    def test_garbage(self):
        assert _safe_float("abc") is None


class TestBuildItem:
    def test_full_valid(self):
        item = _build_item(T_DXY, VALID, "TVC:DXY")
        assert item is not None
        assert item["label"] == "DXY"
        assert item["symbol"] == "TVC:DXY"
        assert item["interval"] == "1d"
        assert item["recommendation"] == "BUY"
        assert item["buy"] == 12
        assert item["sell"] == 5
        assert item["neutral"] == 9
        assert item["osc_recommendation"] == "NEUTRAL"
        assert item["ma_recommendation"] == "STRONG_BUY"
        assert item["rsi"] == 47.2134
        assert item["close"] == 104.13

    def test_none_analysis(self):
        # La lib renvoie None quand TradingView manque de données.
        assert _build_item(T_DXY, None, "TVC:DXY") is None

    def test_missing_summary(self):
        assert _build_item(T_DXY, FakeAnalysis(summary=None), "TVC:DXY") is None

    def test_empty_recommendation(self):
        bad = FakeAnalysis(summary={"RECOMMENDATION": "", "BUY": 0})
        assert _build_item(T_DXY, bad, "TVC:DXY") is None

    def test_partial_indicators(self):
        # Pas d'oscillateurs/MA/indicateurs → item produit, champs optionnels None.
        a = FakeAnalysis(summary={"RECOMMENDATION": "SELL", "BUY": 2, "SELL": 14, "NEUTRAL": 8})
        item = _build_item(T_DXY, a, "TVC:DXY")
        assert item is not None
        assert item["recommendation"] == "SELL"
        assert item["osc_recommendation"] is None
        assert item["ma_recommendation"] is None
        assert item["rsi"] is None
        assert item["close"] is None


class FakeHandler:
    """Remplace TA_Handler : renvoie une analyse fixée ou lève selon le constructeur."""

    raises = False
    result = VALID

    def __init__(self, *args, **kwargs):
        pass

    def get_analysis(self):
        if FakeHandler.raises:
            raise RuntimeError("symbol resolve failed")
        return FakeHandler.result


class TestFetchTargetSync:
    def test_success(self, monkeypatch):
        FakeHandler.raises = False
        FakeHandler.result = VALID
        monkeypatch.setattr(mod, "TA_Handler", FakeHandler)
        ing = TradingViewTAIngester(redis=None)
        item = ing._fetch_target_sync(T_DXY)
        assert item is not None
        assert item["recommendation"] == "BUY"

    def test_library_raises_returns_none(self, monkeypatch):
        FakeHandler.raises = True
        monkeypatch.setattr(mod, "TA_Handler", FakeHandler)
        ing = TradingViewTAIngester(redis=None)
        assert ing._fetch_target_sync(T_DXY) is None
        FakeHandler.raises = False

    def test_analysis_none_returns_none(self, monkeypatch):
        FakeHandler.raises = False
        FakeHandler.result = None
        monkeypatch.setattr(mod, "TA_Handler", FakeHandler)
        ing = TradingViewTAIngester(redis=None)
        assert ing._fetch_target_sync(T_DXY) is None
        FakeHandler.result = VALID

    def test_falls_back_to_second_variant(self, monkeypatch):
        # 1re variante (BAD:X) lève → on doit basculer sur la 2e (TVC:GOLD) qui répond.
        target = TVTarget(
            "Or", "macro", "1d", (("cfd", "BAD", "X"), ("cfd", "TVC", "GOLD"))
        )

        class VariantHandler:
            def __init__(self, *, exchange, symbol, **kwargs):
                self.resolved = f"{exchange}:{symbol}"

            def get_analysis(self):
                if self.resolved == "BAD:X":
                    raise RuntimeError("Exchange or symbol not found.")
                return VALID

        monkeypatch.setattr(mod, "TA_Handler", VariantHandler)
        ing = TradingViewTAIngester(redis=None)
        item = ing._fetch_target_sync(target)
        assert item is not None
        # Le symbole retenu est la variante qui a effectivement répondu.
        assert item["symbol"] == "TVC:GOLD"


class FakeRedis:
    """Faux Redis async minimal : enregistre setex / lpush / ltrim."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.lists: dict[str, list] = {}

    async def setex(self, key, ttl, value):
        self.store[key] = value
        self.ttls[key] = ttl

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start : end + 1]


@pytest.mark.asyncio
class TestCycle:
    async def test_publishes_both_baskets(self, monkeypatch):
        FakeHandler.raises = False
        FakeHandler.result = VALID
        monkeypatch.setattr(mod, "TA_Handler", FakeHandler)
        redis = FakeRedis()
        ing = TradingViewTAIngester(redis=redis)

        await ing._cycle()

        # Les trois clés snapshot (macro + micro BTC + micro GOLD) doivent exister.
        assert REDIS_KEY_MACRO in redis.store
        assert REDIS_KEY_MICRO_BTC in redis.store
        assert REDIS_KEY_MICRO_GOLD in redis.store
        assert redis.ttls[REDIS_KEY_MACRO] == mod.REDIS_TTL_S

        macro = json.loads(redis.store[REDIS_KEY_MACRO])
        assert macro["source"] == "tradingview_ta"
        assert macro["basket"] == "macro"
        assert macro["mode"] == "shadow"
        assert len(macro["items"]) == len(MACRO_TARGETS)
        assert macro["fetched_at"] is not None

        micro_btc = json.loads(redis.store[REDIS_KEY_MICRO_BTC])
        assert micro_btc["basket"] == "micro"
        assert micro_btc["entity"] == "BTC"
        assert len(micro_btc["items"]) == len(MICRO_TARGETS["BTC"])

        micro_gold = json.loads(redis.store[REDIS_KEY_MICRO_GOLD])
        assert micro_gold["entity"] == "GOLD"
        assert len(micro_gold["items"]) == len(MICRO_TARGETS["GOLD"])

        # History alimentée.
        assert len(redis.lists[REDIS_HISTORY_MACRO]) == 1

    async def test_no_data_skips_write(self, monkeypatch):
        # Toutes les cibles échouent → aucun snapshot écrit (on garde le dernier bon).
        FakeHandler.raises = True
        monkeypatch.setattr(mod, "TA_Handler", FakeHandler)
        redis = FakeRedis()
        ing = TradingViewTAIngester(redis=redis)

        await ing._cycle()

        assert REDIS_KEY_MACRO not in redis.store
        assert REDIS_KEY_MICRO_BTC not in redis.store
        assert REDIS_KEY_MICRO_GOLD not in redis.store
        FakeHandler.raises = False
