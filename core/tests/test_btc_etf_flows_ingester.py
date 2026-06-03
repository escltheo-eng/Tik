"""Tests des helpers purs du BtcEtfFlowsIngester (SHADOW, ADR-024).

Aucune dépendance Redis/HTTP : on teste le déballage des champs SoSoValue
(enveloppés `{value,...}` ou bruts), l'extraction de l'enveloppe `{code,msg,data}`,
l'assemblage du snapshot et de la série quotidienne, y compris les cas dégradés.
"""

from tik_core.aggregator.btc_etf_flows_ingester import (
    _build_funds,
    _build_history,
    _build_snapshot,
    _extract_data,
    _unwrap,
)

# Échantillon fidèle à la réponse réelle SoSoValue (currentEtfDataMetrics.data),
# vérifiée depuis le VPS le 2026-06-03.
METRICS = {
    "totalNetAssets": {"value": "84996829511.77", "lastUpdateDate": "2026-06-02", "status": "1"},
    "dailyNetInflow": {"value": "-519190448.94", "lastUpdateDate": "2026-06-02", "status": "1"},
    "cumNetInflow": {"value": "54678021778.23", "lastUpdateDate": "2026-06-02", "status": "1"},
    "dailyTotalValueTraded": {"value": "3926533670.0", "lastUpdateDate": "2026-06-02", "status": "1"},
    "totalTokenHoldings": {"value": "1257585.68745153", "lastUpdateDate": "2026-06-02", "status": "1"},
    "list": [
        {
            "ticker": "IBIT",
            "institute": "BlackRock ",
            "netAssets": {"value": "52179302520.0", "status": "1"},
            "dailyNetInflow": {"value": "-388638720.06", "status": "1"},
            "cumNetInflow": {"value": "62977862223.66", "status": "1"},
        },
        {"ticker": "FBTC", "institute": "Fidelity", "dailyNetInflow": {"value": "-50000000.0"}},
    ],
}
# historicalInflowChart.data : floats BRUTS (pas enveloppés).
CHART = [
    {"date": "2026-06-02", "totalNetInflow": -519190448.94, "cumNetInflow": 54659573505.9,
     "totalNetAssets": 84996829511.7, "totalValueTraded": 3926976133.27},
    {"date": "2026-06-01", "totalNetInflow": -483760871.6, "cumNetInflow": 55178763954.8,
     "totalNetAssets": 91160255779.36, "totalValueTraded": 2963023284.4},
    {"date": "2026-05-29", "totalNetInflow": 120000000.0, "cumNetInflow": 55662524826.4,
     "totalNetAssets": 92000000000.0, "totalValueTraded": 3000000000.0},
]
TS = "2026-06-03T12:00:00+00:00"


class TestUnwrap:
    def test_wrapped(self):
        assert _unwrap({"value": "1.5", "status": "1"}) == 1.5

    def test_raw_float(self):
        assert _unwrap(-519190448.94) == -519190448.94

    def test_none(self):
        assert _unwrap(None) is None

    def test_garbage(self):
        assert _unwrap({"value": "abc"}) is None

    def test_missing_value_key(self):
        assert _unwrap({"status": "1"}) is None


class TestExtractData:
    def test_success(self):
        assert _extract_data({"code": 0, "msg": None, "data": {"x": 1}}) == {"x": 1}

    def test_app_error_code(self):
        # 200 HTTP mais code applicatif ≠ 0 → traité comme échec.
        assert _extract_data({"code": 1001, "msg": "rate limit", "data": None}) is None

    def test_not_a_dict(self):
        assert _extract_data("nope") is None


class TestBuildFunds:
    def test_basic(self):
        funds = _build_funds(METRICS["list"])
        assert len(funds) == 2
        assert funds[0]["ticker"] == "IBIT"
        assert funds[0]["institute"] == "BlackRock"  # strip()
        assert funds[0]["daily_net_inflow_usd"] == -388638720.06
        assert funds[0]["net_assets_usd"] == 52179302520.0
        # Champ manquant → None, pas d'exception.
        assert funds[1]["cum_net_inflow_usd"] is None

    def test_not_a_list(self):
        assert _build_funds({"bad": 1}) == []

    def test_skips_entries_without_ticker(self):
        assert _build_funds([{"institute": "X"}, "garbage", 42]) == []


class TestBuildSnapshot:
    def test_full_valid(self):
        snap = _build_snapshot(METRICS, TS)
        assert snap is not None
        assert snap["source"] == "sosovalue_btc_etf"
        assert snap["entity"] == "BTC"
        assert snap["data_date"] == "2026-06-02"
        assert snap["daily_net_inflow_usd"] == -519190448.94
        assert snap["cum_net_inflow_usd"] == 54678021778.23
        assert snap["total_token_holdings_btc"] == 1257585.68745153
        # Prix BTC implicite = actifs nets / BTC détenus.
        assert snap["implied_btc_price"] == round(84996829511.77 / 1257585.68745153, 2)
        assert snap["n_funds"] == 2
        assert snap["fetched_at"] == TS

    def test_not_a_dict(self):
        assert _build_snapshot("nope", TS) is None

    def test_no_core_data_returns_none(self):
        # Ni flux net quotidien ni cumulé → rien à stocker.
        assert _build_snapshot({"totalNetAssets": {"value": "1"}}, TS) is None

    def test_partial_keeps_snapshot(self):
        # Flux net présent, holdings absent → snapshot produit, implied_btc_price None.
        snap = _build_snapshot({"dailyNetInflow": {"value": "100.0"}}, TS)
        assert snap is not None
        assert snap["daily_net_inflow_usd"] == 100.0
        assert snap["implied_btc_price"] is None
        assert snap["n_funds"] == 0

    def test_zero_holdings_no_divzero(self):
        snap = _build_snapshot(
            {"dailyNetInflow": {"value": "1"}, "totalNetAssets": {"value": "10"},
             "totalTokenHoldings": {"value": "0"}},
            TS,
        )
        assert snap is not None
        assert snap["implied_btc_price"] is None


class TestBuildHistory:
    def test_full_valid(self):
        hist = _build_history(CHART, TS)
        assert hist is not None
        assert hist["source"] == "sosovalue_btc_etf"
        assert hist["n_days"] == 3
        # Trié par date décroissante (plus récent en tête).
        assert hist["daily"][0]["date"] == "2026-06-02"
        assert hist["daily"][-1]["date"] == "2026-05-29"
        assert hist["daily"][0]["net_inflow_usd"] == -519190448.94
        assert hist["fetched_at"] == TS

    def test_cap(self):
        hist = _build_history(CHART, TS, cap=2)
        assert hist is not None
        assert hist["n_days"] == 2
        # Cap garde les 2 plus récents.
        assert {r["date"] for r in hist["daily"]} == {"2026-06-02", "2026-06-01"}

    def test_not_a_list(self):
        assert _build_history({"bad": 1}, TS) is None

    def test_skips_malformed_rows(self):
        chart = [
            {"date": "2026-06-02", "totalNetInflow": 1.0},
            {"totalNetInflow": 2.0},  # pas de date
            {"date": "2026-06-01"},  # pas de flux
            "garbage",
        ]
        hist = _build_history(chart, TS)
        assert hist is not None
        assert hist["n_days"] == 1

    def test_all_malformed_returns_none(self):
        assert _build_history([{"date": "x"}, "y"], TS) is None
