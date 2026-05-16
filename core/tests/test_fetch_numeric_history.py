"""Tests unitaires pour `fetch_numeric_history.py` (P2).

Tests des helpers purs (pas d'appels API live) + tests des 4 fetchers
mockés via `httpx.MockTransport`. Pas d'effets réseau, pas de Redis.
"""

from __future__ import annotations

import pytest
import httpx

from tik_core.scripts.fetch_numeric_history import (
    _dedupe_by_date_avg,
    _gdelt_timespan_from_days,
    _parse_gdelt_date,
    fetch_cot_history,
    fetch_dxy_history,
    fetch_fear_greed_history,
    fetch_gdelt_tone_history,
)


# -------- Helpers purs --------

class TestGdeltTimespanFromDays:
    def test_1y_for_365_days(self):
        assert _gdelt_timespan_from_days(365) == "1y"

    def test_2y_for_730_days(self):
        assert _gdelt_timespan_from_days(730) == "2y"

    def test_6m_for_180_days(self):
        assert _gdelt_timespan_from_days(180) == "6m"

    def test_1m_for_30_days(self):
        assert _gdelt_timespan_from_days(30) == "1m"

    def test_7d_for_7_days(self):
        assert _gdelt_timespan_from_days(7) == "7d"

    def test_1d_for_1_day(self):
        assert _gdelt_timespan_from_days(1) == "1d"


class TestParseGdeltDate:
    def test_full_format_yyyymmddhhmmss(self):
        assert _parse_gdelt_date("20250507120000") == "2025-05-07"

    def test_date_only_yyyymmdd(self):
        assert _parse_gdelt_date("20250507") == "2025-05-07"

    def test_iso_with_separators(self):
        # Tolère les chars non-numériques (strippés)
        assert _parse_gdelt_date("2025-05-07T12:00:00") == "2025-05-07"

    def test_empty_returns_none(self):
        assert _parse_gdelt_date("") is None

    def test_too_short_returns_none(self):
        assert _parse_gdelt_date("2025") is None

    def test_invalid_month_returns_none(self):
        assert _parse_gdelt_date("20251307") is None  # mois 13 invalide

    def test_invalid_day_returns_none(self):
        assert _parse_gdelt_date("20250230") is None  # 30 février


class TestDedupeByDateAvg:
    def test_empty(self):
        assert _dedupe_by_date_avg([]) == []

    def test_no_duplicates(self):
        points = [
            {"date": "2025-05-01", "value": 1.0},
            {"date": "2025-05-02", "value": 2.0},
        ]
        result = _dedupe_by_date_avg(points)
        assert len(result) == 2
        assert result[0]["date"] == "2025-05-01"
        assert result[0]["value"] == 1.0

    def test_duplicates_averaged(self):
        points = [
            {"date": "2025-05-01", "value": 2.0},
            {"date": "2025-05-01", "value": 4.0},
            {"date": "2025-05-02", "value": 6.0},
        ]
        result = _dedupe_by_date_avg(points)
        assert len(result) == 2
        assert result[0]["date"] == "2025-05-01"
        assert result[0]["value"] == 3.0  # (2 + 4) / 2

    def test_sorted_ascending(self):
        points = [
            {"date": "2025-05-03", "value": 1.0},
            {"date": "2025-05-01", "value": 2.0},
            {"date": "2025-05-02", "value": 3.0},
        ]
        result = _dedupe_by_date_avg(points)
        assert [p["date"] for p in result] == ["2025-05-01", "2025-05-02", "2025-05-03"]


# -------- Fetchers mockés --------

@pytest.mark.asyncio
class TestFetchFearGreedHistory:
    async def test_success_response(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "fng" in str(request.url)
            return httpx.Response(200, json={
                "data": [
                    {"value": "30", "value_classification": "Fear", "timestamp": "1715126400"},
                    {"value": "40", "value_classification": "Fear", "timestamp": "1715212800"},
                ]
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_fear_greed_history(days_back=2, client=client)

        assert len(result) == 2
        # Tri ascendant
        assert result[0]["date"] < result[1]["date"]
        assert result[0]["value"] == 30.0
        assert result[1]["value"] == 40.0

    async def test_malformed_payload_skipped(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "data": [
                    {"value": "abc", "value_classification": "X", "timestamp": "1715126400"},
                    {"value": "30", "value_classification": "Fear", "timestamp": "1715212800"},
                ]
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_fear_greed_history(days_back=2, client=client)

        assert len(result) == 1  # le malformé est skippé silencieusement
        assert result[0]["value"] == 30.0

    async def test_http_error_returns_empty(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_fear_greed_history(days_back=2, client=client)

        assert result == []

    async def test_empty_data_returns_empty(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_fear_greed_history(days_back=2, client=client)

        assert result == []


@pytest.mark.asyncio
class TestFetchGdeltToneHistory:
    async def test_success_response(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "timelinetone" in str(request.url)
            return httpx.Response(200, json={
                "timeline": [
                    {
                        "data": [
                            {"date": "20250501000000", "value": -1.5},
                            {"date": "20250502000000", "value": 0.5},
                        ]
                    }
                ]
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_gdelt_tone_history(days_back=30, client=client)

        assert len(result) == 2
        assert result[0]["value"] == -1.5
        assert result[1]["value"] == 0.5

    async def test_429_retry_then_success(self, monkeypatch):
        # Override le backoff minimum pour ne pas ralentir les tests
        # (bug fix P3 GDELT du 2026-05-16 : production utilise 6 s pour
        # respecter le rate-limit GDELT 1 req / 5 s).
        monkeypatch.setattr(
            "tik_core.scripts.fetch_numeric_history.GDELT_MIN_BACKOFF_S",
            0,
        )
        call_count = {"n": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return httpx.Response(429, text="Too Many Requests")
            return httpx.Response(200, json={
                "timeline": [{"data": [{"date": "20250501000000", "value": 1.0}]}]
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_gdelt_tone_history(days_back=30, client=client)

        assert call_count["n"] == 2  # 1 raté + 1 réussi
        assert len(result) == 1

    async def test_429_persistent_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "tik_core.scripts.fetch_numeric_history.GDELT_MIN_BACKOFF_S",
            0,
        )
        call_count = {"n": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(429, text="Too Many Requests")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_gdelt_tone_history(days_back=30, client=client)

        # 4 tentatives totales (initiale + 3 retries)
        assert call_count["n"] == 4
        assert result == []

    async def test_429_backoff_respects_min_floor(self, monkeypatch):
        """Vérifie le fix P3 GDELT (2026-05-16) : le backoff retry est
        capé en bas par GDELT_MIN_BACKOFF_S pour respecter le rate-limit
        GDELT 1 req / 5 s. Sans ce fix, le 1er retry à 2 s retombait
        systématiquement sur 429 et on épuisait les 4 tentatives en 30 s
        sans jamais récupérer la donnée (cause du bug 0 points backtest
        P2). Test : backoff >= GDELT_MIN_BACKOFF_S même si exponentiel
        donnerait moins.
        """
        sleeps: list[float] = []

        async def fake_sleep(s: float) -> None:
            sleeps.append(s)

        monkeypatch.setattr(
            "tik_core.scripts.fetch_numeric_history.asyncio.sleep",
            fake_sleep,
        )
        monkeypatch.setattr(
            "tik_core.scripts.fetch_numeric_history.GDELT_MIN_BACKOFF_S",
            6,
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="Too Many Requests")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await fetch_gdelt_tone_history(days_back=30, client=client)

        # 3 retries → 3 backoffs. Pattern attendu : max(6, 2^(n+1))
        # → max(6, 2)=6, max(6, 4)=6, max(6, 8)=8
        assert sleeps == [6, 6, 8]

    async def test_malformed_timeline_returns_empty(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"timeline": "not a list"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_gdelt_tone_history(days_back=30, client=client)

        assert result == []


@pytest.mark.asyncio
class TestFetchDxyHistory:
    async def test_success_response(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "fred" in str(request.url) or "stlouisfed" in str(request.url)
            return httpx.Response(200, json={
                "observations": [
                    {"date": "2025-05-01", "value": "120.5"},
                    {"date": "2025-05-02", "value": "121.0"},
                    {"date": "2025-05-03", "value": "."},  # FRED missing data
                ]
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_dxy_history(api_key="fake_key", days_back=30, client=client)

        # Le "." est skippé
        assert len(result) == 2
        assert result[0]["value"] == 120.5
        assert result[1]["value"] == 121.0

    async def test_no_api_key_returns_empty(self):
        result = await fetch_dxy_history(api_key="", days_back=30)
        assert result == []

    async def test_http_error_returns_empty(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Server Error")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_dxy_history(api_key="k", days_back=30, client=client)

        assert result == []


@pytest.mark.asyncio
class TestFetchCotHistory:
    async def test_success_response(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[
                {
                    "report_date_as_yyyy_mm_dd": "2026-05-01T00:00:00.000",
                    "m_money_positions_long_all": "100000",
                    "m_money_positions_short_all": "50000",
                },
                {
                    "report_date_as_yyyy_mm_dd": "2026-04-24T00:00:00.000",
                    "m_money_positions_long_all": "90000",
                    "m_money_positions_short_all": "60000",
                },
            ])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_cot_history(days_back=60, client=client)

        # Tri ascendant après dédup, dates strippées du T-suffix
        assert len(result) == 2
        assert result[0]["date"] == "2026-04-24"
        # Net pct = (long - short) / total
        assert result[0]["value"] == round((90000 - 60000) / 150000, 4)

    async def test_zero_positions_skipped(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[
                {
                    "report_date_as_yyyy_mm_dd": "2026-05-01T00:00:00.000",
                    "m_money_positions_long_all": "0",
                    "m_money_positions_short_all": "0",
                },
            ])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_cot_history(days_back=60, client=client)

        assert result == []

    async def test_old_data_filtered_by_cutoff(self):
        # Une row très vieille doit être filtrée par days_back=30
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[
                {
                    "report_date_as_yyyy_mm_dd": "2020-01-01T00:00:00.000",
                    "m_money_positions_long_all": "100000",
                    "m_money_positions_short_all": "50000",
                },
            ])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_cot_history(days_back=30, client=client)

        assert result == []

    async def test_unexpected_payload_returns_empty(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "wrong format"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_cot_history(days_back=60, client=client)

        assert result == []
