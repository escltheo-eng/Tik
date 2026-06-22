"""Tests du Cross-asset ingester (ADR-032) — fonctions pures + schéma.

Pas de Redis/HTTP : on teste la LOGIQUE (parse Yahoo, ALIGNEMENT des dates BTC 7j/7
vs TradFi semaine, corrélation, label de comportement) + le schéma. CONTEXTE strict.

⭐ Test central : l'alignement sur dates communes (sinon corrélation fausse).
"""

from tik_core.aggregator.cross_asset_ingester import (
    aligned_returns,
    compute_cross_asset,
    parse_chart,
    pearson,
)
from tik_core.storage.schemas import CrossAssetOut

TS_20260101 = 1767225600  # 2026-01-01 00:00 UTC


def _mk_chart(closes: list, start_ts: int = TS_20260101) -> dict:
    """JSON Yahoo synthétique : 1 point/jour (None = close manquant)."""
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [start_ts + i * 86400 for i in range(len(closes))],
                    "indicators": {"quote": [{"close": closes}]},
                }
            ]
        }
    }


class TestParseChart:
    def test_basic_and_skip_null(self):
        out = parse_chart(_mk_chart([100.0, None, 102.0]))
        assert out == {"2026-01-01": 100.0, "2026-01-03": 102.0}

    def test_malformed(self):
        assert parse_chart({}) == {}
        assert parse_chart({"chart": {"result": []}}) == {}


class TestAlignedReturns:
    def test_aligns_on_common_dates(self):
        # BTC a un point le 2026-01-02 (week-end) que l'actif TradFi n'a pas.
        btc = {"2026-01-01": 100.0, "2026-01-02": 110.0, "2026-01-03": 121.0}
        asset = {"2026-01-01": 50.0, "2026-01-03": 55.0}  # pas de 01-02
        br, orr = aligned_returns(btc, asset)
        # Dates communes = {01-01, 01-03} → 1 rendement chacune.
        assert len(br) == 1 and len(orr) == 1
        # BTC : 121/100 − 1 = 0.21 (le saut du 02 est absorbé) ; asset : 55/50 − 1 = 0.10
        assert abs(br[0] - 0.21) < 1e-9
        assert abs(orr[0] - 0.10) < 1e-9

    def test_too_few_common(self):
        assert aligned_returns({"a": 1.0}, {"b": 2.0}) == ([], [])


class TestPearson:
    def test_perfect_positive(self):
        xs = [0.01, 0.02, -0.01, 0.03]
        ys = [0.02, 0.04, -0.02, 0.06]  # = 2*xs → corr +1
        assert pearson(xs, ys) == 1.0

    def test_perfect_negative(self):
        xs = [0.01, 0.02, -0.01, 0.03]
        ys = [-0.01, -0.02, 0.01, -0.03]  # = -xs → corr -1
        assert pearson(xs, ys) == -1.0

    def test_too_few_or_flat(self):
        assert pearson([0.1, 0.2], [0.1, 0.2]) is None  # < 3
        assert pearson([0.1, 0.1, 0.1], [0.2, 0.3, 0.4]) is None  # variance nulle → None


class TestComputeCrossAsset:
    def _btc_and_perfect(self, mult: float):
        # BTC croissant + un actif parfaitement (anti)corrélé selon `mult`.
        days = 40
        btc = {f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}": 100.0 * (1.02**i) for i in range(days)}
        asset = {d: 50.0 * (1 + mult * (v / 100.0 - 1)) for d, v in btc.items()}
        return btc, asset

    def test_risk_asset_when_equities_lead(self):
        btc, sp = self._btc_and_perfect(1.0)  # corrélé +1 aux actions
        _, gold = self._btc_and_perfect(-1.0)  # or anticorrélé
        out = compute_cross_asset(
            btc, [("sp500", "S&P 500", sp), ("gold", "Or", gold)]
        )
        assert out["available"] is True
        assert out["behavior"] == "risk_asset"
        sp_row = next(a for a in out["assets"] if a["key"] == "sp500")
        assert sp_row["corr_recent"] == 1.0

    def test_digital_gold_when_gold_leads(self):
        btc, gold = self._btc_and_perfect(1.0)
        _, sp = self._btc_and_perfect(-1.0)
        out = compute_cross_asset(btc, [("sp500", "S&P 500", sp), ("gold", "Or", gold)])
        assert out["behavior"] == "digital_gold"

    def test_decoupled_when_uncorrelated(self):
        # Deux motifs de rendements ORTHOGONAUX (corr exactement 0) → découplé.
        # BTC : +,-,+,-,…  ;  actif : +,+,-,-,…  → produits = +,-,-,+,… → somme 0.
        dates = [f"2026-02-{1 + i:02d}" for i in range(9)]  # 9 dates → 8 rendements
        btc_mult = [1.01, 0.99, 1.01, 0.99, 1.01, 0.99, 1.01, 0.99]
        asset_mult = [1.01, 1.01, 0.99, 0.99, 1.01, 1.01, 0.99, 0.99]
        btc, asset = {dates[0]: 100.0}, {dates[0]: 50.0}
        bv, av = 100.0, 50.0
        for i, d in enumerate(dates[1:]):
            bv *= btc_mult[i]
            av *= asset_mult[i]
            btc[d], asset[d] = bv, av
        out = compute_cross_asset(btc, [("sp500", "S&P 500", asset)])
        assert out["assets"][0]["corr_recent"] == 0.0  # orthogonaux
        assert out["behavior"] == "decoupled"

    def test_empty_btc(self):
        assert compute_cross_asset({}, [("sp500", "S&P 500", {"a": 1.0})]) == {"available": False}

    def test_skips_assets_with_too_little_data(self):
        btc = {f"2026-01-{1 + i:02d}": 100.0 + i for i in range(20)}
        out = compute_cross_asset(btc, [("sp500", "S&P 500", {"2026-01-01": 5.0})])
        assert out["assets"] == []  # 1 point commun → < 5 rendements → ignoré


class TestCrossAssetSchema:
    def test_construct_and_extra_ignored(self):
        out = CrossAssetOut(
            available=True,
            as_of="2026-06-20",
            behavior="risk_asset",
            assets=[
                {"key": "sp500", "label": "S&P 500", "corr_recent": 0.62, "corr_full": 0.55, "n": 30},
                {"key": "gold", "label": "Or", "corr_recent": 0.1, "junk": 1},  # extra ignoré
            ],
        )
        assert out.behavior == "risk_asset"
        assert len(out.assets) == 2
        assert out.assets[0].corr_recent == 0.62
        assert out.assets[1].label == "Or"

    def test_empty_when_unavailable(self):
        out = CrossAssetOut(available=False)
        assert out.available is False
        assert out.assets == []
