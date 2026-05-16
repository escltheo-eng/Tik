"""Helpers async pour récupérer l'historique 6-12 mois des sources numériques.

Utilisé par `backtest_numeric_sources.py` (P2 plan stratégique fiabilité).
Aucun ingester ne persistait l'historique long terme — chaque helper appelle
directement l'API publique de la source.

Format de retour uniforme : list[dict] avec au minimum `date` (ISO 8601) et
`value` (float). Extras spécifiques selon la source.

Erreurs : best-effort, retourne [] avec log warning si l'API est down.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

# URLs et constantes (alignées sur les ingesters existants)
FNG_URL = "https://api.alternative.me/fng/"
GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"
DXY_SERIES_ID = "DTWEXBGS"
CFTC_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
GOLD_COMEX_CODE = "088691"

GDELT_USER_AGENT = "tik-osint-bot/0.1 (research; contact escltheo@gmail.com)"

# GDELT impose un rate limit de 1 requête / 5 secondes par IP (cf. message
# d'erreur 429 "Please limit requests to one every 5 seconds"). Le backoff
# du retry doit donc respecter ce minimum, sinon le 1er retry retombe sur
# 429 et on épuise les 4 tentatives avant que la fenêtre rate-limit se
# libère. Cause racine du bug Paquet 19 P2 backtest GDELT 0 points (cf.
# CLAUDE.md investigation P3 du 2026-05-16). Module-level pour permettre
# le monkey-patch dans les tests (sinon backoff 6 s × 3 retries = 18 s par
# test 429 = trop lent).
GDELT_MIN_BACKOFF_S = 6


async def fetch_fear_greed_history(
    days_back: int = 365,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Récupère l'historique Fear & Greed Index sur N jours.

    API alternative.me supporte `limit=N` pour les N derniers points (1 par jour).
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20.0)

    try:
        try:
            r = await client.get(FNG_URL, params={"limit": days_back})
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("fetch_fg_history.error", error=str(exc))
            return []

        points: list[dict[str, Any]] = []
        for raw in data.get("data", []):
            try:
                ts_unix = int(raw["timestamp"])
                value = int(raw["value"])
                classification = str(raw["value_classification"])
            except (KeyError, TypeError, ValueError):
                continue
            date = datetime.fromtimestamp(ts_unix, tz=timezone.utc).date().isoformat()
            points.append({
                "date": date,
                "value": float(value),
                "classification": classification,
            })

        # API renvoie en ordre desc → ascendant pour cohérence
        points.sort(key=lambda p: p["date"])
        return points
    finally:
        if own_client:
            await client.aclose()


async def fetch_gdelt_tone_history(
    query: str = "gold price",
    days_back: int = 365,
    lang: str = "eng",
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Récupère l'historique du tone GDELT sur N jours via mode `timelinetone`.

    GDELT auto-buckets selon le timespan : sur 1y, granularité ~daily.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)

    timespan = _gdelt_timespan_from_days(days_back)
    params = {
        "query": f"{query} sourcelang:{lang}",
        "mode": "timelinetone",
        "format": "json",
        "timespan": timespan,
    }

    try:
        # Retry simple avec backoff exponentiel sur 429 (rate-limit GDELT)
        data = None
        for attempt in range(4):
            try:
                r = await client.get(
                    GDELT_DOC_API_URL,
                    params=params,
                    headers={"User-Agent": GDELT_USER_AGENT},
                    follow_redirects=True,
                )
                r.raise_for_status()
                data = r.json()
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt < 3:
                    # Cf. constante GDELT_MIN_BACKOFF_S ci-dessus pour le
                    # raisonnement (1 req / 5 s GDELT, fix bug 0 points
                    # backtest P2). Backoff = max(min, exponentiel).
                    backoff_s = max(GDELT_MIN_BACKOFF_S, 2 ** (attempt + 1))
                    log.warning(
                        "fetch_gdelt_history.rate_limited",
                        attempt=attempt + 1,
                        backoff_s=backoff_s,
                    )
                    await asyncio.sleep(backoff_s)
                    continue
                log.warning(
                    "fetch_gdelt_history.error",
                    error=str(exc),
                    query=query,
                    timespan=timespan,
                )
                return []
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "fetch_gdelt_history.error",
                    error=str(exc),
                    query=query,
                    timespan=timespan,
                )
                return []
        if data is None:
            log.warning("fetch_gdelt_history.no_data_after_retries", query=query)
            return []

        points: list[dict[str, Any]] = []
        timeline = data.get("timeline") or []
        if not isinstance(timeline, list):
            return []
        for series in timeline:
            if not isinstance(series, dict):
                continue
            entries = series.get("data") or []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                date_raw = entry.get("date")
                value_raw = entry.get("value")
                if date_raw is None or value_raw is None:
                    continue
                date_iso = _parse_gdelt_date(str(date_raw))
                if date_iso is None:
                    continue
                try:
                    value = float(value_raw)
                except (TypeError, ValueError):
                    continue
                points.append({"date": date_iso, "value": value})

        # GDELT peut retourner plusieurs séries — on déduplique par date (moyenne)
        return _dedupe_by_date_avg(points)
    finally:
        if own_client:
            await client.aclose()


async def fetch_dxy_history(
    api_key: str,
    days_back: int = 365,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Récupère l'historique du DXY (DTWEXBGS) sur N jours via FRED API.

    DTWEXBGS est mis à jour quotidiennement (jours ouvrés US uniquement).
    Sur 12 mois → ~252 points (jours ouvrés sur 365 calendaires).
    """
    if not api_key:
        log.warning("fetch_dxy_history.no_api_key")
        return []

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20.0)

    end_date = datetime.now(tz=timezone.utc).date()
    start_date = end_date - timedelta(days=days_back)

    try:
        try:
            r = await client.get(
                FRED_OBS_URL,
                params={
                    "series_id": DXY_SERIES_ID,
                    "api_key": api_key,
                    "file_type": "json",
                    "observation_start": start_date.isoformat(),
                    "observation_end": end_date.isoformat(),
                    "sort_order": "asc",
                },
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("fetch_dxy_history.error", error=str(exc))
            return []

        points: list[dict[str, Any]] = []
        for obs in data.get("observations", []):
            date_raw = obs.get("date")
            value_raw = obs.get("value")
            if date_raw is None or value_raw in (".", "", None):
                continue
            try:
                value = float(value_raw)
            except (TypeError, ValueError):
                continue
            points.append({"date": str(date_raw), "value": value})
        return points
    finally:
        if own_client:
            await client.aclose()


async def fetch_cot_history(
    days_back: int = 365,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Récupère l'historique CFTC COT GOLD COMEX sur N jours.

    Rapport hebdomadaire (vendredi, snapshot mardi précédent). Sur 12m → ~52 points.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)

    # Limit généreux : ~60 semaines pour avoir plus que 12m si quelques rows
    # manquent. On filtrera ensuite côté Python par date_cutoff.
    weeks_to_fetch = max(60, (days_back // 7) + 8)
    cutoff = (datetime.now(tz=timezone.utc).date() - timedelta(days=days_back)).isoformat()

    try:
        try:
            r = await client.get(
                CFTC_URL,
                params={
                    "$where": f"cftc_contract_market_code='{GOLD_COMEX_CODE}'",
                    "$order": "report_date_as_yyyy_mm_dd DESC",
                    "$limit": weeks_to_fetch,
                },
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("fetch_cot_history.error", error=str(exc))
            return []

        if not isinstance(data, list):
            log.warning("fetch_cot_history.unexpected_payload", data_type=type(data).__name__)
            return []

        points: list[dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            try:
                mm_long = int(row["m_money_positions_long_all"])
                mm_short = int(row["m_money_positions_short_all"])
                report_date = str(row["report_date_as_yyyy_mm_dd"])
            except (KeyError, TypeError, ValueError):
                continue
            total = mm_long + mm_short
            if total == 0:
                continue
            net_pct = (mm_long - mm_short) / total
            # report_date est ISO datetime du Socrata (T00:00:00.000), on garde la date
            date_only = report_date.split("T")[0] if "T" in report_date else report_date
            if date_only < cutoff:
                continue
            points.append({
                "date": date_only,
                "value": round(net_pct, 4),
                "mm_long": mm_long,
                "mm_short": mm_short,
            })

        # API renvoie desc → ascendant
        points.sort(key=lambda p: p["date"])
        return points
    finally:
        if own_client:
            await client.aclose()


# Helpers internes


def _gdelt_timespan_from_days(days_back: int) -> str:
    """Convertit jours en format timespan GDELT (1y / 6m / 30d / etc.)."""
    if days_back >= 365:
        years = max(1, days_back // 365)
        return f"{years}y"
    if days_back >= 30:
        months = max(1, days_back // 30)
        return f"{months}m"
    return f"{days_back}d"


def _parse_gdelt_date(raw: str) -> str | None:
    """GDELT dates : `YYYYMMDDHHMMSS` ou `YYYYMMDD`. On garde YYYY-MM-DD ISO."""
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) < 8:
        return None
    try:
        year = int(digits[:4])
        month = int(digits[4:6])
        day = int(digits[6:8])
        return datetime(year, month, day).date().isoformat()
    except (ValueError, IndexError):
        return None


def _dedupe_by_date_avg(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Si plusieurs valeurs pour la même date (séries multiples GDELT), moyenne."""
    if not points:
        return []
    by_date: dict[str, list[float]] = {}
    for p in points:
        by_date.setdefault(p["date"], []).append(p["value"])
    result = [
        {"date": date, "value": sum(vals) / len(vals)}
        for date, vals in by_date.items()
    ]
    result.sort(key=lambda p: p["date"])
    return result


# CLI helper pour tester rapidement
if __name__ == "__main__":
    import argparse
    import asyncio
    import os

    parser = argparse.ArgumentParser(description="Test fetch helpers (CLI debug)")
    parser.add_argument("--source", required=True, choices=["fg", "gdelt", "dxy", "cot"])
    parser.add_argument("--days-back", type=int, default=365)
    parser.add_argument("--query", default="gold price", help="Query GDELT")
    parser.add_argument("--max-show", type=int, default=10)
    args = parser.parse_args()

    async def run() -> None:
        if args.source == "fg":
            data = await fetch_fear_greed_history(days_back=args.days_back)
        elif args.source == "gdelt":
            data = await fetch_gdelt_tone_history(query=args.query, days_back=args.days_back)
        elif args.source == "dxy":
            api_key = os.environ.get("FRED_API_KEY", "")
            data = await fetch_dxy_history(api_key=api_key, days_back=args.days_back)
        else:
            data = await fetch_cot_history(days_back=args.days_back)
        print(f"Total points: {len(data)}")
        if data:
            print(f"First: {json.dumps(data[0])}")
            print(f"Last: {json.dumps(data[-1])}")
            print(f"Sample (max {args.max_show}):")
            for p in data[:args.max_show]:
                print(f"  {json.dumps(p)}")

    asyncio.run(run())
