"""Tests du Macro Regime (ADR-028) — fonctions pures + schémas + helpers cockpit.

Pas de Redis/HTTP : on teste la LOGIQUE (calcul net liquidity, régime) et la
construction des schémas, à la manière de test_derivatives_api.py.

⭐ Test central : le PIÈGE DES UNITÉS du Fed Net Liquidity. WALCL et TGA sont en
MILLIONS de $, RRP en MILLIARDS de $. Oublier la normalisation = erreur ×1000.
"""

from tik_core.aggregator.macro_regime_ingester import (
    _rrp_for_date,
    _series_metrics,
    _value_on_or_before,
    compute_global_liquidity_series,
    compute_global_regime,
    compute_net_liquidity_series,
    compute_regime,
    compute_risk_regime,
    latest_valid,
    parse_observations,
)
from tik_core.api.macro import _polymarket_summary, _subset
from tik_core.storage.schemas import MacroRegimeOut, RiskRegimeOut


def _mk_weekly(values: list[float], start: str = "2026-01-07") -> list[tuple[str, float]]:
    """Construit une série (date_iso, value) sur des mercredis successifs."""
    from datetime import date, timedelta

    d0 = date.fromisoformat(start)
    return [((d0 + timedelta(days=7 * i)).isoformat(), v) for i, v in enumerate(values)]


class TestParseObservations:
    def test_skips_missing(self):
        obs = [
            {"date": "2026-06-10", "value": "6725397"},
            {"date": "2026-06-03", "value": "."},  # manquant FRED
            {"date": "2026-05-27", "value": ""},
            {"date": "2026-05-20", "value": "6700000"},
        ]
        out = parse_observations(obs)
        assert out == {"2026-06-10": 6725397.0, "2026-05-20": 6700000.0}

    def test_latest_valid(self):
        assert latest_valid({"2026-01-01": 1.0, "2026-06-10": 4.45}) == ("2026-06-10", 4.45)
        assert latest_valid({}) is None


class TestRrpForDate:
    def test_same_day(self):
        rrp = {"2026-06-10": 0.5}
        assert _rrp_for_date(rrp, "2026-06-10") == 0.5

    def test_back_search_within_window(self):
        # RRP absent le mercredi 06-10, présent le lundi 06-08 → trouvé (≤ 7 j).
        rrp = {"2026-06-08": 0.7}
        assert _rrp_for_date(rrp, "2026-06-10") == 0.7

    def test_too_far_returns_none(self):
        rrp = {"2026-05-01": 0.7}
        assert _rrp_for_date(rrp, "2026-06-10") is None


class TestNetLiquidityUnitsGotcha:
    """⭐ Le test qui protège contre l'erreur d'un facteur 1000."""

    def test_normalization_to_billions(self):
        # Données réelles 2026-06-15 : WALCL/TGA en MILLIONS, RRP en MILLIARDS.
        walcl = {"2026-06-10": 6_725_397.0}  # millions → 6725.397 Md$
        tga = {"2026-06-10": 828_122.0}  # millions → 828.122 Md$
        rrp = {"2026-06-10": 0.5}  # DÉJÀ en milliards
        series = compute_net_liquidity_series(walcl, tga, rrp)
        assert len(series) == 1
        date_, net = series[0]
        assert date_ == "2026-06-10"
        # 6725.397 − 828.122 − 0.5 = 5896.775 → 5896.8 Md$ (~5.90 T$)
        assert net == 5896.8
        # Garde-fou explicite : sans normalisation /1000 on aurait des millions.
        assert net < 10_000  # milliards, PAS millions

    def test_aligns_on_shared_wednesday_dates(self):
        walcl = {"2026-06-10": 6_725_397.0, "2026-06-03": 6_700_000.0}
        tga = {"2026-06-10": 828_122.0}  # 06-03 absent côté TGA
        rrp = {"2026-06-10": 0.5, "2026-06-03": 0.4}
        series = compute_net_liquidity_series(walcl, tga, rrp)
        # Seule la date partagée 06-10 produit un point.
        assert [d for d, _ in series] == ["2026-06-10"]

    def test_missing_rrp_defaults_zero(self):
        walcl = {"2026-06-10": 6_725_397.0}
        tga = {"2026-06-10": 828_122.0}
        series = compute_net_liquidity_series(walcl, tga, {})  # RRP vide
        # net = 6725.397 − 828.122 − 0 = 5897.275 → 5897.3
        assert series[0][1] == 5897.3


class TestValueOnOrBefore:
    def test_same_day_and_back_search(self):
        s = {"2026-06-05": 1.15, "2026-06-01": 1.10}
        assert _value_on_or_before(s, "2026-06-05") == 1.15
        assert _value_on_or_before(s, "2026-06-07") == 1.15  # 2 j en arrière
        assert _value_on_or_before(s, "2026-06-03", max_back=2) == 1.10  # 2 j arrière
        assert _value_on_or_before(s, "2026-06-20", max_back=7) is None  # trop loin


class TestGlobalLiquidityUnitsGotcha:
    """⭐ Conversions FX + le piège BoJ « 100 Mio ¥ »."""

    def test_conversion_to_usd_billions(self):
        # Données réelles 2026-06-15 (cadences différentes alignées sur WALCL).
        walcl = {"2026-06-10": 6_725_397.0}  # millions USD
        ecb = {"2026-06-05": 6_136_317.0}  # millions EUR (hebdo, 5 j avant)
        boj = {"2026-05-01": 6_643_630.0}  # « 100 millions ¥ » (mensuel, 40 j avant)
        eurusd = {"2026-06-10": 1.1533}  # USD pour 1 €
        jpyusd = {"2026-06-10": 160.26}  # ¥ pour 1 $
        series = compute_global_liquidity_series(walcl, ecb, boj, eurusd, jpyusd)
        assert len(series) == 1
        date_, gl = series[0]
        assert date_ == "2026-06-10"
        # même arithmétique que l'ingester (pin de correctness)
        expected = round(
            (6_725_397.0 + 6_136_317.0 * 1.1533 + 6_643_630.0 * 100.0 / 160.26) / 1000.0, 1
        )
        assert gl == expected
        # ordre de grandeur ~18 T$ (≈ 18 000 Md$) — garde-fou anti-mauvaise-unité
        assert 17_000 < gl < 19_000

    def test_boj_x100_matters(self):
        # Sans le ×100 sur la BoJ, le total chuterait de ~4000 Md$ → ce test
        # échouerait, ce qui prouve que la conversion BoJ est bien appliquée.
        walcl = {"2026-06-10": 6_725_397.0}
        ecb = {"2026-06-10": 6_000_000.0}
        boj = {"2026-06-10": 6_600_000.0}  # 100 Mio ¥
        eurusd = {"2026-06-10": 1.15}
        jpyusd = {"2026-06-10": 160.0}
        gl = compute_global_liquidity_series(walcl, ecb, boj, eurusd, jpyusd)[0][1]
        boj_contrib = 6_600_000.0 * 100.0 / 160.0 / 1000.0  # ~4125 Md$
        assert boj_contrib > 4_000  # le ×100 donne bien des milliers de Md$

    def test_skips_when_component_missing(self):
        walcl = {"2026-06-10": 6_725_397.0}
        # pas de FX → aucun point produit
        series = compute_global_liquidity_series(
            walcl, {"2026-06-10": 6e6}, {"2026-06-10": 6e6}, {}, {}
        )
        assert series == []


class TestComputeGlobalRegime:
    def test_keys_and_regime(self):
        from datetime import date, timedelta

        d0 = date.fromisoformat("2026-01-07")
        series = [
            ((d0 + timedelta(days=7 * i)).isoformat(), 17000.0 + i * 50) for i in range(20)
        ]
        out = compute_global_regime(series)
        assert out["available"] is True
        assert out["global_liquidity_busd"] == 17950.0
        assert out["global_liquidity_tusd"] == 17.95
        assert "net_liquidity_busd" not in out  # clés bien distinctes du net liquidity
        assert out["regime"] == "expansion"

    def test_empty(self):
        assert compute_global_regime([]) == {"available": False}


class TestComputeRegime:
    def test_empty(self):
        assert compute_regime([]) == {"available": False}

    def test_expansion(self):
        series = _mk_weekly([5000 + i * 20 for i in range(20)])  # croissance régulière
        out = compute_regime(series)
        assert out["available"] is True
        assert out["regime"] == "expansion"
        assert out["net_liquidity_busd"] == 5380.0
        assert out["delta_13w_busd"] == 260.0  # 5380 − 5120 (13 pas en arrière)
        assert out["delta_4w_busd"] == 80.0  # 5380 − 5300 (4 pas en arrière)
        assert out["zscore_52w"] > 0  # dernier point = max → z positif
        assert out["context_only"] is True

    def test_contraction(self):
        series = _mk_weekly([5400 - i * 20 for i in range(20)])  # décroissance
        out = compute_regime(series)
        assert out["regime"] == "contraction"
        assert out["delta_13w_busd"] < 0

    def test_neutral_flat(self):
        series = _mk_weekly([5000.0] * 20)  # plat
        out = compute_regime(series)
        assert out["regime"] == "neutral"
        assert out["delta_13w_busd"] == 0.0
        assert out["zscore_52w"] == 0.0  # std nul → z = 0

    def test_unknown_when_too_short(self):
        series = _mk_weekly([5000.0, 5010.0, 5020.0])  # < 14 points
        out = compute_regime(series)
        assert out["regime"] == "unknown"
        assert out["delta_13w_busd"] is None


def _mk_daily(values: list[float], start: str = "2025-06-02") -> dict[str, float]:
    """Construit une série quotidienne {date_iso: value} sur jours consécutifs."""
    from datetime import date, timedelta

    d0 = date.fromisoformat(start)
    return {(d0 + timedelta(days=i)).isoformat(): v for i, v in enumerate(values)}


class TestSeriesMetrics:
    def test_ascending_percentile_and_delta(self):
        # 40 valeurs croissantes 1..40 → dernière = max → centile 1.0.
        m = _series_metrics(_mk_daily([float(i) for i in range(1, 41)]))
        assert m is not None
        assert m["value"] == 40.0
        assert m["n"] == 40
        assert m["pct_rank_1y"] == 1.0  # dernier point = sommet
        assert m["delta_20d"] == 20.0  # 40 − values[-21] (=20)
        assert m["zscore_1y"] > 0

    def test_descending_low_percentile(self):
        # 40 valeurs décroissantes 40..1 → dernière = min → centile bas.
        m = _series_metrics(_mk_daily([float(i) for i in range(40, 0, -1)]))
        assert m is not None
        assert m["value"] == 1.0
        assert m["pct_rank_1y"] == round(1 / 40, 2)  # seul lui-même est ≤ lui

    def test_short_series_no_rank(self):
        # < 30 points → pas de centile/z-score (mais value présente).
        m = _series_metrics(_mk_daily([10.0, 11.0, 12.0]))
        assert m is not None
        assert m["value"] == 12.0
        assert m["pct_rank_1y"] is None
        assert m["zscore_1y"] is None

    def test_empty_returns_none(self):
        assert _series_metrics({}) is None


class TestComputeRiskRegime:
    def test_risk_off_high_stress(self):
        # VIX + HY tous deux au sommet → centile moyen 1.0 ≥ 0.70 → risk_off.
        asc = _mk_daily([float(i) for i in range(1, 41)])
        out = compute_risk_regime(asc, asc, asc)
        assert out["available"] is True
        assert out["risk_state"] == "risk_off"
        assert out["stress_percentile"] == 1.0
        assert out["vix"]["series_id"] == "VIXCLS"
        assert out["hy_oas"]["series_id"] == "BAMLH0A0HYM2"
        assert out["as_of"] == max(asc)  # dernière date
        assert out["context_only"] is True

    def test_risk_on_calm(self):
        # VIX + HY au plancher → centile bas ≤ 0.30 → risk_on.
        desc = _mk_daily([float(i) for i in range(40, 0, -1)])
        out = compute_risk_regime(desc, desc, desc)
        assert out["risk_state"] == "risk_on"
        assert out["stress_percentile"] <= 0.30

    def test_neutral_mixed(self):
        # VIX au sommet (1.0), HY au plancher (~0.03) → moyenne ~0.51 → neutral.
        asc = _mk_daily([float(i) for i in range(1, 41)])
        desc = _mk_daily([float(i) for i in range(40, 0, -1)])
        out = compute_risk_regime(asc, desc, {})
        assert out["risk_state"] == "neutral"
        assert 0.30 < out["stress_percentile"] < 0.70

    def test_ig_excluded_from_label(self):
        # IG fourni mais NE compte PAS dans le label (seuls VIX+HY le décident).
        asc = _mk_daily([float(i) for i in range(1, 41)])
        desc = _mk_daily([float(i) for i in range(40, 0, -1)])
        # VIX sommet, HY absent → label sur VIX seul (1.0) → risk_off, IG (bas) ignoré.
        out = compute_risk_regime(asc, {}, desc)
        assert out["risk_state"] == "risk_off"
        assert out["ig_oas"]["series_id"] == "BAMLC0A0CM"  # exposé en détail

    def test_unknown_when_too_short(self):
        # Séries trop courtes → pas de centile → state unknown (mais available True).
        short = _mk_daily([10.0, 11.0, 12.0])
        out = compute_risk_regime(short, short, short)
        assert out["available"] is True
        assert out["risk_state"] == "unknown"
        assert out["stress_percentile"] is None

    def test_empty_all(self):
        assert compute_risk_regime({}, {}, {}) == {"available": False}


class TestRiskRegimeSchema:
    def test_construct_and_extra_ignored(self):
        out = RiskRegimeOut(
            available=True,
            as_of="2026-06-19",
            risk_state="risk_off",
            stress_percentile=0.82,
            vix={"value": 21.4, "date": "2026-06-19", "pct_rank_1y": 0.8, "series_id": "VIXCLS"},
            hy_oas={"value": 3.6, "date": "2026-06-19", "pct_rank_1y": 0.84},
        )
        assert out.risk_state == "risk_off"
        assert out.vix.value == 21.4
        assert out.hy_oas.pct_rank_1y == 0.84
        assert out.ig_oas is None

    def test_risk_regime_survives_in_macro_blob(self):
        blob = {
            "available": True,
            "risk_regime": {
                "available": True,
                "risk_state": "neutral",
                "stress_percentile": 0.5,
                "vix": {"value": 16.0, "date": "2026-06-19", "series_id": "VIXCLS"},
            },
        }
        out = MacroRegimeOut(**blob)
        assert out.risk_regime is not None
        assert out.risk_regime.risk_state == "neutral"
        assert out.risk_regime.vix.value == 16.0


class TestMacroRegimeSchema:
    def test_construct_from_blob(self):
        blob = {
            "source": "fred_macro_regime",
            "fetched_at": "2026-06-15T13:00:00+00:00",
            "context_only": True,
            "net_liquidity": {
                "available": True,
                "as_of": "2026-06-10",
                "net_liquidity_busd": 5896.8,
                "net_liquidity_tusd": 5.897,
                "delta_13w_busd": -120.0,
                "regime": "contraction",
                "components": {"walcl_busd": 6725.4, "rrp_busd": 0.5},
            },
            "indicators": {
                "real_rate_10y": {"value": 2.16, "date": "2026-06-11", "series_id": "DFII10"},
                "recession_prob_12m": {"value": 0.44, "date": "2026-04-01"},
            },
        }
        out = MacroRegimeOut(**{**blob, "available": True})
        assert out.available is True
        assert out.net_liquidity.regime == "contraction"
        assert out.net_liquidity.net_liquidity_tusd == 5.897
        assert out.indicators["real_rate_10y"].value == 2.16
        assert out.indicators["recession_prob_12m"].date == "2026-04-01"

    def test_empty_when_unavailable(self):
        out = MacroRegimeOut(available=False)
        assert out.available is False
        assert out.net_liquidity is None
        assert out.indicators == {}


class TestCockpitHelpers:
    def test_subset(self):
        d = {"a": 1, "b": 2, "c": 3}
        assert _subset(d, ["a", "c"]) == {"a": 1, "c": 3}
        assert _subset(None, ["a"]) is None
        # champ absent → None (pas de KeyError)
        assert _subset({"a": 1}, ["a", "z"]) == {"a": 1, "z": None}

    def test_polymarket_summary(self):
        payload = {
            "n_events": 4,
            "total_volume": 61576442.86,
            "fetched_at": "2026-06-15T13:04:01+00:00",
            "events": [
                {"title": f"E{i}", "end_date": "2026-06-15T16:00:00Z", "markets": [1, 2]}
                for i in range(5)
            ],
        }
        out = _polymarket_summary(payload)
        assert out["n_events"] == 4
        assert out["total_volume"] == 61576442.86
        assert len(out["events"]) == 3  # cappé à 3
        assert out["events"][0] == {"title": "E0", "end_date": "2026-06-15T16:00:00Z"}
        assert _polymarket_summary(None) is None
