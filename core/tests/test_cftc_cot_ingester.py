"""Tests unitaires de l'ingester CFTC COT.

On teste la méthode `_fetch` de l'ingester en injectant un transport
HTTP mocké (httpx.MockTransport) — pas besoin d'un vrai appel réseau.

Couvre :
- parsing du JSON Socrata réel (échantillon GOLD COMEX 2026-04-21)
- calcul du net_pct (long - short) / (long + short)
- gestion des cas d'erreur : réponse vide, champs manquants, total = 0,
  HTTP 5xx
"""

import httpx
import pytest

from tik_core.aggregator.cftc_cot_ingester import (
    CFTC_URL,
    GOLD_COMEX_CODE,
    CftcCotIngester,
)

# ----- Helpers -----


def _make_ingester() -> CftcCotIngester:
    """Crée un ingester sans Redis (on ne teste que _fetch ici)."""
    return CftcCotIngester(redis=None, interval_s=86400)  # type: ignore[arg-type]


def _client_with_handler(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


# Échantillon réduit du payload Socrata réel récupéré le 2026-04-21
_SAMPLE_ROW = {
    "id": "260421088691F",
    "market_and_exchange_names": "GOLD - COMMODITY EXCHANGE INC.",
    "report_date_as_yyyy_mm_dd": "2026-04-21T00:00:00.000",
    "cftc_contract_market_code": "088691",
    "commodity_name": "GOLD",
    "m_money_positions_long_all": "123681",
    "m_money_positions_short_all": "30705",
    "change_in_m_money_long_all": "-1741",
    "change_in_m_money_short_all": "424",
}


# ----- _fetch : cas nominal -----


async def test_fetch_parses_valid_response():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=[_SAMPLE_ROW])

    ingester = _make_ingester()
    async with _client_with_handler(handler) as client:
        result = await ingester._fetch(client)

    # URL et filtres bien construits
    assert CFTC_URL in captured["url"]
    assert GOLD_COMEX_CODE in captured["url"]
    assert "report_date_as_yyyy_mm_dd" in captured["url"]

    assert result is not None
    assert result["source"] == "cftc_cot"
    assert result["commodity"] == "gold"
    assert result["report_date"] == "2026-04-21T00:00:00.000"
    assert result["mm_long"] == 123681
    assert result["mm_short"] == 30705
    # net_pct = (123681 - 30705) / (123681 + 30705) ≈ 0.6022
    assert result["mm_net_pct"] == pytest.approx(0.6022, abs=1e-3)
    assert result["change_mm_long"] == -1741
    assert result["change_mm_short"] == 424
    assert "fetched_at" in result


async def test_fetch_computes_balanced_net_pct():
    row = {
        **_SAMPLE_ROW,
        "m_money_positions_long_all": "50000",
        "m_money_positions_short_all": "50000",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row])

    ingester = _make_ingester()
    async with _client_with_handler(handler) as client:
        result = await ingester._fetch(client)

    assert result is not None
    assert result["mm_net_pct"] == 0.0


async def test_fetch_computes_extreme_short_net_pct():
    row = {
        **_SAMPLE_ROW,
        "m_money_positions_long_all": "10000",
        "m_money_positions_short_all": "90000",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row])

    ingester = _make_ingester()
    async with _client_with_handler(handler) as client:
        result = await ingester._fetch(client)

    assert result is not None
    assert result["mm_net_pct"] == pytest.approx(-0.8, abs=1e-3)


# ----- _fetch : cas d'erreur -----


async def test_fetch_returns_none_on_empty_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    ingester = _make_ingester()
    async with _client_with_handler(handler) as client:
        result = await ingester._fetch(client)
    assert result is None


async def test_fetch_returns_none_on_zero_total_positions():
    """Garde-fou : long=0 et short=0 ne doit pas crasher (division par zéro)."""
    row = {**_SAMPLE_ROW, "m_money_positions_long_all": "0", "m_money_positions_short_all": "0"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row])

    ingester = _make_ingester()
    async with _client_with_handler(handler) as client:
        result = await ingester._fetch(client)
    assert result is None


async def test_fetch_returns_none_on_missing_field():
    row = {k: v for k, v in _SAMPLE_ROW.items() if k != "m_money_positions_long_all"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row])

    ingester = _make_ingester()
    async with _client_with_handler(handler) as client:
        result = await ingester._fetch(client)
    assert result is None


async def test_fetch_returns_none_on_invalid_value_type():
    row = {**_SAMPLE_ROW, "m_money_positions_long_all": "not-a-number"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row])

    ingester = _make_ingester()
    async with _client_with_handler(handler) as client:
        result = await ingester._fetch(client)
    assert result is None


async def test_fetch_returns_none_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal"})

    ingester = _make_ingester()
    async with _client_with_handler(handler) as client:
        result = await ingester._fetch(client)
    assert result is None


async def test_fetch_handles_missing_change_fields_gracefully():
    """Les champs `change_in_*` sont optionnels — défaut 0."""
    row = {k: v for k, v in _SAMPLE_ROW.items() if not k.startswith("change_in_")}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row])

    ingester = _make_ingester()
    async with _client_with_handler(handler) as client:
        result = await ingester._fetch(client)

    assert result is not None
    assert result["change_mm_long"] == 0
    assert result["change_mm_short"] == 0
