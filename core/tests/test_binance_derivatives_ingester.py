"""Tests du helper pur du BinanceDerivativesIngester (SHADOW, ADR-023).

Aucune dépendance Redis/HTTP : on teste l'assemblage déterministe du snapshot
à partir des 4 réponses Binance (premiumIndex / openInterest / globalLongShort /
topLongShort), y compris les cas de sous-appels partiellement échoués.
"""

from tik_core.aggregator.binance_derivatives_ingester import _build_snapshot, _safe_float

PREMIUM = {
    "lastFundingRate": "0.00003704",
    "markPrice": "67059.90000000",
    "nextFundingTime": 1780502400000,
}
OPEN_INTEREST = {"openInterest": "107582.876", "time": 1780487403835}
GLOBAL_LS = [
    {"longShortRatio": "2.0000", "longAccount": "0.6667", "shortAccount": "0.3333", "timestamp": 1},
    {"longShortRatio": "2.1949", "longAccount": "0.6870", "shortAccount": "0.3130", "timestamp": 2},
]
TOP_LS = [{"longShortRatio": "2.2279", "longAccount": "0.6902", "shortAccount": "0.3098"}]
TS = "2026-06-03T12:00:00+00:00"


class TestSafeFloat:
    def test_valid_str(self):
        assert _safe_float("1.5") == 1.5

    def test_none(self):
        assert _safe_float(None) is None

    def test_garbage(self):
        assert _safe_float("abc") is None


class TestBuildSnapshot:
    def test_full_valid(self):
        snap = _build_snapshot(PREMIUM, OPEN_INTEREST, GLOBAL_LS, TOP_LS, TS)
        assert snap is not None
        assert snap["source"] == "binance_derivatives"
        assert snap["entity"] == "BTC"
        assert snap["funding_rate"] == 0.00003704
        assert snap["mark_price"] == 67059.9
        assert snap["open_interest_btc"] == 107582.876
        # USD = OI_btc * mark_price, arrondi 2 décimales.
        assert snap["open_interest_usd"] == round(107582.876 * 67059.9, 2)
        # L/S = dernier élément de la liste (le plus récent).
        assert snap["long_short_ratio_global"] == 2.1949
        assert snap["long_account_global"] == 0.6870
        assert snap["long_short_ratio_top"] == 2.2279
        assert snap["fetched_at"] == TS

    def test_only_premium(self):
        # OI absent → snapshot quand même produit (funding présent), oi_usd None.
        snap = _build_snapshot(PREMIUM, None, None, None, TS)
        assert snap is not None
        assert snap["funding_rate"] == 0.00003704
        assert snap["open_interest_btc"] is None
        assert snap["open_interest_usd"] is None
        assert snap["long_short_ratio_global"] is None

    def test_only_open_interest(self):
        # premium absent → pas de mark_price → oi_usd impossible mais oi_btc présent.
        snap = _build_snapshot(None, OPEN_INTEREST, None, None, TS)
        assert snap is not None
        assert snap["funding_rate"] is None
        assert snap["open_interest_btc"] == 107582.876
        assert snap["open_interest_usd"] is None

    def test_no_core_data_returns_none(self):
        # Ni funding ni OI → rien à stocker.
        assert _build_snapshot(None, None, GLOBAL_LS, TOP_LS, TS) is None

    def test_ls_empty_list(self):
        snap = _build_snapshot(PREMIUM, OPEN_INTEREST, [], [], TS)
        assert snap is not None
        assert snap["long_short_ratio_global"] is None
        assert snap["long_short_ratio_top"] is None

    def test_ls_not_a_list(self):
        snap = _build_snapshot(PREMIUM, OPEN_INTEREST, {"bad": 1}, None, TS)
        assert snap is not None
        assert snap["long_short_ratio_global"] is None

    def test_non_numeric_funding(self):
        bad_premium = {"lastFundingRate": "abc", "markPrice": "67000"}
        snap = _build_snapshot(bad_premium, OPEN_INTEREST, None, None, TS)
        assert snap is not None
        assert snap["funding_rate"] is None
        # OI présent → snapshot valide, et oi_usd calculable via markPrice.
        assert snap["mark_price"] == 67000.0
        assert snap["open_interest_usd"] == round(107582.876 * 67000.0, 2)

    def test_premium_not_a_dict(self):
        snap = _build_snapshot("nope", OPEN_INTEREST, None, None, TS)
        assert snap is not None
        assert snap["funding_rate"] is None
        assert snap["open_interest_btc"] == 107582.876
