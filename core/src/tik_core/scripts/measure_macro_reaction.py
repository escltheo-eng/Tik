"""Mesure SHADOW — réaction HISTORIQUE de BTC/GOLD aux events macro US (lecture seule).

But
---
Répondre, de façon DESCRIPTIVE et honnête, à : « après tel event macro (NFP, CPI,
FOMC…), comment BTC et GOLD ont-ils historiquement bougé ? ». C'est du CONTEXTE
OSINT (couche macro/fondamentale : events publics FRED + prix publics), PAS de
l'analyse technique, PAS un edge tradeable. N'écrit RIEN, ne touche ni au pipeline
ni à Redis ni à la base `signals`. Conforme à la règle SHADOW vs ENRÔLEMENT
(`docs/backlog-osint.md`) : mesurer ≠ enrôler.

Méthode (v1 — granularité JOURNALIÈRE)
--------------------------------------
- Dates des events : FRED `/release/dates` pour la whitelist `FRED_RELEASES`
  (NFP, CPI, PPI, GDP, Retail Sales, Industrial Production, Initial Claims).
- Prix : klines **journalières** BTC (Binance, ~2.7 ans) + GOLD (Yahoo, 5 ans).
- Réaction = variation signée vs la clôture de la veille de l'event :
    same_day = close(jour de l'event) / close(veille) − 1
    +1d, +3d = close(J+1 / J+3) / close(veille) − 1
  (on prend le 1er jour de bourse disponible on-or-after pour gérer les week-ends
  côté GOLD ; BTC est 24/7 donc exact).
- Agrégat par type d'event : N, médiane signée, % du temps à la hausse, |move| moyen.

Pourquoi journalier (et pas +1h/+4h)
------------------------------------
Découverte 2026-05-28 : Yahoo ne fournit l'intraday GOLD que ~60 jours en arrière
→ un échantillon intraday sur des années est IMPOSSIBLE pour GOLD. Le journalier
est la seule granularité où BTC ET GOLD ont un historique long et comparable.
L'intraday (le pic dans les minutes après l'annonce, là où c'est le plus fort)
fera l'objet d'une v2 BTC-only sur fenêtre récente.

Limites majeures (engagement 13bis #8)
--------------------------------------
1. **DESCRIPTIF, pas prédictif** : la réaction moyenne passée ne garantit pas la
   prochaine. Aucun edge n'est revendiqué.
2. **Échantillon modeste** : ~24-36 occurrences par event mensuel sur la fenêtre
   prix dispo. Les events trop anciens (> dispo BTC) sont droppés côté BTC.
3. **Non conditionné sur la SURPRISE** : un CPI conforme ne bouge rien, un gros
   écart bouge fort. Ici on poole tout (surprise inconnue). Le conditionnement
   sur la surprise (actual vs forecast) est le job de
   `measure_forexfactory_surprise.py` (BTC, N minuscule). v2 : fusionner.
4. **Journalier dilue le pic intraday** (cf. ci-dessus).
5. **FOMC absent en v1** : pas de série FRED `/release/dates` équivalente ; les
   dates FOMC statiques (`FOMC_STATIC_DATES`) ne couvrent que le futur. v2.

Usage
-----
    docker exec tik-core python -m tik_core.scripts.measure_macro_reaction
    docker exec tik-core python -m tik_core.scripts.measure_macro_reaction --limit 60
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from datetime import UTC, datetime, timedelta

import httpx

from tik_core.aggregator.macro_calendar_data import FRED_RELEASES
from tik_core.config import get_settings
from tik_core.scripts.backtest import fetch_btc_history, fetch_gold_history

FRED_DATES_URL = "https://api.stlouisfed.org/fred/release/dates"
HORIZONS = (("same_day", 0), ("+1d", 1), ("+3d", 3))


async def fetch_release_dates(
    client: httpx.AsyncClient, api_key: str, release_id: int, limit: int
) -> list[datetime]:
    """Dernières `limit` dates de publication d'un release FRED (UTC, naïf→aware).

    sort_order=desc + realtime_end=9999-12-31 : cf. fred_calendar_ingester (asc
    récupère les dates depuis 1776, aucune récente).
    """
    r = await client.get(
        FRED_DATES_URL,
        params={
            "release_id": release_id,
            "api_key": api_key,
            "file_type": "json",
            "realtime_end": "9999-12-31",
            "sort_order": "desc",
            "limit": limit,
            "include_release_dates_with_no_data": "false",
        },
        timeout=30.0,
    )
    r.raise_for_status()
    data = r.json()
    out: list[datetime] = []
    for d in data.get("release_dates", []):
        try:
            out.append(datetime.strptime(d["date"], "%Y-%m-%d").replace(tzinfo=UTC))
        except (KeyError, ValueError):
            continue
    return out


def date_close_map(history: list[tuple[int, float]]) -> dict:
    """{date UTC: clôture journalière}. Une bougie 1d = une date."""
    m: dict = {}
    for ts_ms, price in history:
        d = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).date()
        m[d] = price
    return m


def _close_on_or_after(m: dict, day: datetime, max_fwd: int = 5) -> float | None:
    for i in range(max_fwd + 1):
        p = m.get((day + timedelta(days=i)).date())
        if p is not None:
            return p
    return None


def _close_on_or_before(m: dict, day: datetime, max_back: int = 5) -> float | None:
    for i in range(max_back + 1):
        p = m.get((day - timedelta(days=i)).date())
        if p is not None:
            return p
    return None


def reaction(m: dict, event_day: datetime) -> dict | None:
    """Variations signées (%) vs la clôture de la veille, par horizon. None si pas de baseline."""
    base = _close_on_or_before(m, event_day - timedelta(days=1))
    if base is None or base == 0:
        return None
    out: dict = {}
    for label, off in HORIZONS:
        p = _close_on_or_after(m, event_day + timedelta(days=off))
        out[label] = (p - base) / base * 100 if p is not None else None
    return out


def aggregate(moves: list[float | None]) -> dict | None:
    vals = [m for m in moves if m is not None]
    if not vals:
        return None
    return {
        "n": len(vals),
        "median": statistics.median(vals),
        "pct_up": 100 * sum(1 for v in vals if v > 0) / len(vals),
        "mean_abs": statistics.fmean(abs(v) for v in vals),
    }


def _fmt(agg: dict | None) -> str:
    if agg is None:
        return "        n/a        "
    return f"n={agg['n']:>3} méd={agg['median']:+.2f}% haut={agg['pct_up']:>3.0f}% |{agg['mean_abs']:.2f}%|"


async def fetch_price_maps(client: httpx.AsyncClient) -> tuple[dict, dict]:
    """Maps {date: clôture} BTC (Binance 1d, ~2.7 ans) et GOLD (Yahoo 1d, 5 ans)."""
    btc = date_close_map(await fetch_btc_history(client, interval="1d", limit=1000))
    gold = date_close_map(await fetch_gold_history(client, interval="1d", range_param="5y"))
    return btc, gold


async def compute_event_reactions(
    client: httpx.AsyncClient,
    api_key: str,
    *,
    limit: int = 48,
    price_maps: tuple[dict, dict] | None = None,
) -> dict:
    """Réaction historique par event FRED — réutilisable (script ET endpoint).

    Retour : {event_code: {"event_name", "importance", "n_dates",
              "assets": {"BTC": {label: agg|None}, "GOLD": {...}}}}.
    Un event dont le fetch des dates échoue est simplement absent du dict.
    """
    if price_maps is None:
        price_maps = await fetch_price_maps(client)
    btc, gold = price_maps
    out: dict = {}
    for spec in FRED_RELEASES:
        try:
            dates = await fetch_release_dates(client, api_key, spec.release_id, limit)
        except Exception:  # noqa: BLE001
            continue
        assets: dict = {}
        for asset, m in (("BTC", btc), ("GOLD", gold)):
            reactions = [r for d in dates if (r := reaction(m, d)) is not None]
            assets[asset] = {
                label: aggregate([r[label] for r in reactions]) for label, _ in HORIZONS
            }
        out[spec.event_code] = {
            "event_name": spec.event_name,
            "importance": spec.importance,
            "n_dates": len(dates),
            "assets": assets,
        }
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(
        description="Réaction historique BTC/GOLD aux events macro US (shadow)."
    )
    ap.add_argument("--limit", type=int, default=48, help="Nb de dates FRED par event (défaut 48).")
    args = ap.parse_args()

    api_key = get_settings().fred_api_key
    if not api_key:
        print("ERREUR : TIK_FRED_API_KEY absent — impossible de récupérer les dates d'events.")
        return 1

    async with httpx.AsyncClient() as client:
        price_maps = await fetch_price_maps(client)
        btc, gold = price_maps
        btc_span = f"{min(btc)} → {max(btc)}" if btc else "vide"
        gold_span = f"{min(gold)} → {max(gold)}" if gold else "vide"

        print("=" * 78)
        print("  RÉACTION HISTORIQUE BTC / GOLD AUX EVENTS MACRO US — SHADOW (descriptif)")
        print("=" * 78)
        print(f"  BTC daily  : {len(btc)} jours ({btc_span})")
        print(f"  GOLD daily : {len(gold)} jours ({gold_span})")
        print("  Lecture : méd = médiane du move signé vs clôture veille · haut = % du")
        print("            temps à la hausse · |x%| = amplitude moyenne. NON conditionné")
        print("            sur la surprise · descriptif, PAS un edge.")
        print("=" * 78)

        reactions_by_event = await compute_event_reactions(
            client, api_key, limit=args.limit, price_maps=price_maps
        )
        for spec in FRED_RELEASES:
            ev = reactions_by_event.get(spec.event_code)
            if ev is None:
                print(f"\n{spec.event_code} : pas de données (fetch dates échoué)")
                continue
            print(
                f"\n### {spec.event_code} ({ev['event_name']}, {ev['importance']}) "
                f"— {ev['n_dates']} dates FRED"
            )
            for asset in ("BTC", "GOLD"):
                line = f"  {asset:<4} "
                for label, _ in HORIZONS:
                    line += f"| {label}: {_fmt(ev['assets'][asset][label])} "
                print(line)

    print("\n" + "=" * 78)
    print("  Rappels : descriptif (pas prédictif) · journalier (pic intraday non capté)")
    print("  · surprise non conditionnée · FOMC absent v1 · échantillon modeste.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
