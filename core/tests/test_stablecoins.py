"""Tests du Stablecoins ingester (ADR-031) — fonctions pures + schéma.

Pas de Redis/HTTP : on teste la LOGIQUE (parsing chart DefiLlama, calcul tendance,
répartition) + la construction du schéma. CONTEXTE strict (ne touche aucun signal).
"""

from tik_core.aggregator.stablecoins_ingester import (
    compute_stablecoin_regime,
    parse_breakdown,
    parse_chart_series,
)
from tik_core.storage.schemas import StablecoinsOut

# 2026-01-01 00:00 UTC en epoch (point de départ des séries de test).
TS_20260101 = 1767225600


def _mk_chart(values: list[float], start_ts: int = TS_20260101) -> list[dict]:
    """Série DefiLlama synthétique : 1 point/jour, peggedUSD en Md$ → USD."""
    return [
        {"date": str(start_ts + i * 86400), "totalCirculatingUSD": {"peggedUSD": v * 1e9}}
        for i, v in enumerate(values)
    ]


class TestParseChartSeries:
    def test_basic_conversion_and_sort(self):
        raw = _mk_chart([300.0, 301.0, 302.5])
        s = parse_chart_series(raw)
        assert s == [("2026-01-01", 300.0), ("2026-01-02", 301.0), ("2026-01-03", 302.5)]

    def test_skips_malformed_and_missing(self):
        raw = [
            {"date": "1767225600", "totalCirculatingUSD": {"peggedUSD": 300e9}},
            {"date": "bad", "totalCirculatingUSD": {"peggedUSD": 1e9}},  # date invalide
            {"date": "1767312000", "totalCirculatingUSD": {}},  # peggedUSD absent
            {"date": "1767398400"},  # totalCirculatingUSD absent
        ]
        s = parse_chart_series(raw)
        assert s == [("2026-01-01", 300.0)]

    def test_empty(self):
        assert parse_chart_series([]) == []
        assert parse_chart_series(None) == []


class TestComputeStablecoinRegime:
    def test_expansion(self):
        s = parse_chart_series(_mk_chart([300.0 + i * 0.5 for i in range(40)]))
        out = compute_stablecoin_regime(s)
        assert out["available"] is True
        assert out["total_busd"] == 319.5  # 300 + 39*0.5
        assert out["total_tusd"] == 0.32  # round(319.5/1000, 3)
        assert out["delta_30d_busd"] == 15.0  # 319.5 − 304.5 (30 pas en arrière)
        assert out["delta_7d_busd"] == 3.5  # 319.5 − 316.0
        assert out["pct_30d"] > 0.5
        assert out["trend"] == "expansion"
        assert out["context_only"] is True

    def test_contraction(self):
        s = parse_chart_series(_mk_chart([320.0 - i * 0.5 for i in range(40)]))
        out = compute_stablecoin_regime(s)
        assert out["trend"] == "contraction"
        assert out["delta_30d_busd"] < 0

    def test_neutral_flat(self):
        s = parse_chart_series(_mk_chart([310.0] * 40))
        out = compute_stablecoin_regime(s)
        assert out["trend"] == "neutral"
        assert out["pct_30d"] == 0.0
        assert out["zscore_90d"] == 0.0  # std nul

    def test_unknown_when_too_short(self):
        s = parse_chart_series(_mk_chart([300.0, 301.0, 302.0]))  # < 31 points
        out = compute_stablecoin_regime(s)
        assert out["trend"] == "unknown"
        assert out["delta_30d_busd"] is None
        assert out["pct_30d"] is None

    def test_empty(self):
        assert compute_stablecoin_regime([]) == {"available": False}


class TestParseBreakdown:
    def _raw(self):
        return {
            "peggedAssets": [
                {"symbol": "USDC", "name": "USD Coin", "circulating": {"peggedUSD": 75e9}},
                {"symbol": "USDT", "name": "Tether", "circulating": {"peggedUSD": 186e9}},
                {"symbol": "DAI", "name": "Dai", "circulating": {"peggedUSD": 4e9}},
                {"symbol": "EURe", "name": "Euro", "circulating": {"peggedEUR": 1e9}},  # pas USD
            ]
        }

    def test_sorted_desc_and_share(self):
        out = parse_breakdown(self._raw(), top_n=3)
        assert [x["symbol"] for x in out] == ["USDT", "USDC", "DAI"]  # tri desc
        # part = circ / total USD-pegged (186+75+4 = 265 Md ; EURe compte 0 en peggedUSD)
        assert out[0]["circulating_busd"] == 186.0
        assert abs(out[0]["share"] - 186.0 / 265.0) < 0.01

    def test_top_n_cap(self):
        assert len(parse_breakdown(self._raw(), top_n=2)) == 2

    def test_empty(self):
        assert parse_breakdown({}) == []
        assert parse_breakdown(None) == []


class TestStablecoinsSchema:
    def test_construct_and_extra_ignored(self):
        blob = {
            "available": True,
            "source": "defillama_stablecoins",
            "as_of": "2026-06-20",
            "total_busd": 313.4,
            "total_tusd": 0.313,
            "delta_30d_busd": 2.1,
            "pct_30d": 0.67,
            "trend": "expansion",
            "zscore_90d": 1.2,
            "breakdown": [
                {"symbol": "USDT", "name": "Tether", "circulating_busd": 186.4, "share": 0.59},
                {"symbol": "USDC", "circulating_busd": 74.9, "share": 0.24, "junk": 1},  # extra ignoré
            ],
            "context_only": True,
        }
        out = StablecoinsOut(**blob)
        assert out.available is True
        assert out.trend == "expansion"
        assert out.total_tusd == 0.313
        assert len(out.breakdown) == 2
        assert out.breakdown[0].symbol == "USDT"
        assert out.breakdown[1].share == 0.24

    def test_empty_when_unavailable(self):
        out = StablecoinsOut(available=False)
        assert out.available is False
        assert out.breakdown == []
        assert out.trend is None
