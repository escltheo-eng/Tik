"""Mesure SHADOW de la valeur prédictive de la SURPRISE macro — lecture seule.

Contexte
--------
L'archiveur `archive_forexfactory.py` tourne en SHADOW (cron 2 h) et préserve le
`forecast` (= consensus de marché) du calendrier ForexFactory, qui est la partie
PÉRISSABLE (feed rolling-week). Ce script LIT cette archive + les `actual`
publiés par FRED, calcule la **surprise = actual − forecast** par event US, et
tente de mesurer si la surprise a une valeur prédictive sur le prix BTC à venir
(IC Spearman / hit de signe / gain), à plusieurs horizons.

Il n'écrit RIEN, ne touche ni au pipeline, ni à Redis, ni à la base `signals`.
Conforme à la règle SHADOW vs ENRÔLEMENT (`docs/backlog-osint.md`) : mesurer ≠
enrôler. Le go/no-go directionnel du 2026-05-27 est NO-GO → aucune source ne
s'enrôle sur la direction tant que ce n'est pas mesuré ≥ 2 semaines + régime mixte.

Pourquoi FRED pour l'`actual`
-----------------------------
Vérifié 2026-05-27 (curl VPS) : le feed ForexFactory `thisweek` n'expose AUCUN
champ `actual` (clés réelles = title/country/date/impact/forecast/previous). Il
fournit le consensus, pas le réalisé. FRED fournit le réalisé (historique, non
périssable) mais pas le consensus. On les JOINT :

    surprise = actual_FRED − forecast_FF   (dans l'unité du forecast FF)

avec conversion d'unités par type d'event (indice → % m/m, niveau → variation,
GDP déjà en % annualisé, etc.). Couverture US uniquement (les events non-US du
feed n'ont pas d'actual FRED) — cf. `US_EVENT_MAP`.

`actual` pending
----------------
Un event tout juste publié n'a pas encore son obs FRED (FRED a un délai). Dans
ce cas `derive_actual` renvoie None ("pending") : on ne fabrique PAS une surprise
à partir de l'obs du mois précédent (ce serait un faux positif). La paire devient
mesurable une fois FRED à jour ET l'horizon prix écoulé.

Limites majeures (à garder en tête — engagement 13bis #8)
---------------------------------------------------------
1. **N minuscule au démarrage** : archive depuis 2026-05-26, events HIGH US
   rares (~1-3/semaine). Tout IC est PRÉLIMINAIRE et non concluant. Re-lancer
   après ≥ 2 semaines (et idéalement un NFP + un CPI + un FOMC).
2. **Normalisation cross-event provisoire** : on poole des events de natures
   différentes (NFP en milliers, CPI en %). Le signal poolé est la surprise
   RELATIVE `(actual−forecast)/|forecast|` (sans dimension, sign-preserving) —
   v1 à réviser quand il y aura des données (z-score par type d'event).
3. **BTC seulement** : la surprise macro US frappe surtout GOLD/DXY, mais GOLD
   est gêné par Yahoo (délai 15 min + week-end). BTC (24/7, klines Binance) est
   l'actif propre pour un premier instrument. GOLD = extension future.
4. **Conversion d'unités par event** = le vrai morceau délicat (cf. Polymarket
   « M de May »). Les helpers de conversion sont testés unitairement contre des
   valeurs FRED connues ; étendre `US_EVENT_MAP` avec prudence (series_id vérifié).

Usage
-----
    docker exec tik-core python -m tik_core.scripts.measure_forexfactory_surprise
    docker exec tik-core python -m tik_core.scripts.measure_forexfactory_surprise --min-pairs 20
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from bisect import bisect_right
from datetime import date, datetime

import httpx

from tik_core.config import get_settings
from tik_core.scripts.archive_forexfactory import SNAPSHOTS_FILE
from tik_core.scripts.backtest_numeric_sources import spearman_correlation
from tik_core.utils.time import now_utc

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
PRICE_TOL_MS = 90 * 60 * 1000  # 90 min de tolérance (klines 1h)
HORIZONS_H = (1, 6, 24)  # horizons forward mesurés (heures)

# --- Mapping event US -> (série FRED, périodicité, dérivation d'unité) ---------
# TOUS les series_id ci-dessous ont été vérifiés actifs (curl FRED, 2026-05-27).
# unit:
#   "direct"      -> l'obs FRED EST déjà la valeur attendue (UNRATE %, GDP % annualisé)
#   "mom_pct"     -> (obs[ref]/obs[ref-1m] - 1) * 100  (indices/niveaux: CPI, PCE, retail...)
#   "yoy_pct"     -> (obs[ref]/obs[ref-12m] - 1) * 100
#   "mom_diff_k"  -> obs[ref] - obs[ref-1m]  (PAYEMS déjà en milliers, FF forecast en "K")
# period: "monthly" | "quarterly"
US_EVENT_MAP: dict[str, tuple[str, str, str]] = {
    "core pce price index m/m": ("PCEPILFE", "monthly", "mom_pct"),
    "pce price index m/m": ("PCEPI", "monthly", "mom_pct"),
    "cpi m/m": ("CPIAUCSL", "monthly", "mom_pct"),
    "core cpi m/m": ("CPILFESL", "monthly", "mom_pct"),
    "cpi y/y": ("CPIAUCSL", "monthly", "yoy_pct"),
    "core cpi y/y": ("CPILFESL", "monthly", "yoy_pct"),
    "non-farm employment change": ("PAYEMS", "monthly", "mom_diff_k"),
    "unemployment rate": ("UNRATE", "monthly", "direct"),
    "average hourly earnings m/m": ("CES0500000003", "monthly", "mom_pct"),
    "retail sales m/m": ("RSAFS", "monthly", "mom_pct"),
    "ppi m/m": ("PPIFIS", "monthly", "mom_pct"),
    "personal spending m/m": ("PCE", "monthly", "mom_pct"),
    "personal income m/m": ("PI", "monthly", "mom_pct"),
    "prelim gdp q/q": ("A191RL1Q225SBEA", "quarterly", "direct"),
    "advance gdp q/q": ("A191RL1Q225SBEA", "quarterly", "direct"),
    "final gdp q/q": ("A191RL1Q225SBEA", "quarterly", "direct"),
}

# Suffixe collé au nombre uniquement (pas de \s* — leçon bug Polymarket « M de May »),
# et pas suivi d'une lettre. Capture signe + nombre + suffixe d'échelle optionnel.
_VALUE_RE = re.compile(r"^\s*([+-]?[\d,]+(?:\.\d+)?)\s*([kKmMbBtT%]?)(?![A-Za-z])")
_SCALE = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


def parse_macro_value(s: str | None) -> float | None:
    """Parse un forecast/previous FF en float.

    Conventions FF : '0.3%'->0.3 (le % n'est PAS appliqué, c'est l'unité),
    '150K'->150 (le K reste l'unité 'milliers' du forecast NFP, donc 150),
    '-3.8M'->-3.8, '96B'->96, '91.9'->91.9, '4'->4, ''->None.

    Important : pour '%' on garde la valeur nominale (0.3, pas 0.003) car le
    forecast FF EST exprimé en points de % et on le compare à un actual lui aussi
    en points de % (cf. derive_actual mom_pct). Idem K/M/B : on garde l'échelle
    nominale du tableau FF (NFP forecast '150K' = 150, comparé à PAYEMS diff en
    milliers). On NE multiplie donc PAS par l'échelle — le suffixe n'est qu'un
    indicateur d'unité partagé entre forecast et actual.
    """
    if not s or not isinstance(s, str):
        return None
    m = _VALUE_RE.match(s)
    if not m:
        return None
    num = m.group(1).replace(",", "")
    try:
        return float(num)
    except ValueError:
        return None


def normalize_title(t: str | None) -> str:
    """Titre normalisé pour le lookup US_EVENT_MAP (lowercase, espaces compactés)."""
    if not t:
        return ""
    return re.sub(r"\s+", " ", t.strip().lower())


def parse_iso(s: str | None) -> datetime | None:
    """ISO-8601 tolérant (Z, +00:00, ou offset explicite type -04:00). Aware ou None."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _add_months(d: date, n: int) -> date:
    """Ajoute n mois (n<0 pour soustraire) à un date, jour ramené au 1er."""
    total = (d.year * 12 + (d.month - 1)) + n
    return date(total // 12, total % 12 + 1, 1)


def expected_reference_date(release_dt: datetime, period: str) -> date:
    """Date de l'obs FRED que la release ALIMENTE (1er du mois/trimestre de réf).

    - monthly : un indicateur publié au mois M couvre le mois M-1.
      Core PCE release 2026-05-28 -> réf 2026-04-01.
    - quarterly : couvre le dernier trimestre ACHEVÉ avant la release.
      Prelim GDP release 2026-05-28 (Q2) -> dernier trimestre achevé = Q1 -> 2026-01-01.
    """
    rd = release_dt.date()
    if period == "monthly":
        return _add_months(date(rd.year, rd.month, 1), -1)
    if period == "quarterly":
        cur_q_start_month = ((rd.month - 1) // 3) * 3 + 1
        cur_q_start = date(rd.year, cur_q_start_month, 1)
        return _add_months(cur_q_start, -3)  # trimestre précédent
    raise ValueError(f"période inconnue: {period}")


def derive_actual(obs_by_date: dict[date, float], ref_date: date, unit: str) -> float | None:
    """Dérive l'actual dans l'unité du forecast FF. None si donnée pas (encore) publiée.

    obs_by_date : {date_obs (1er du mois/trim) : valeur}. ref_date doit être présent,
    sinon FRED n'a pas encore publié cette période -> None (pending), PAS de surprise
    fabriquée à partir d'une période antérieure.
    """
    cur = obs_by_date.get(ref_date)
    if cur is None:
        return None
    if unit == "direct":
        return cur
    if unit == "mom_pct":
        prev = obs_by_date.get(_add_months(ref_date, -1))
        if prev in (None, 0):
            return None
        return (cur / prev - 1.0) * 100.0
    if unit == "yoy_pct":
        prev = obs_by_date.get(_add_months(ref_date, -12))
        if prev in (None, 0):
            return None
        return (cur / prev - 1.0) * 100.0
    if unit == "mom_diff_k":
        prev = obs_by_date.get(_add_months(ref_date, -1))
        if prev is None:
            return None
        return cur - prev
    raise ValueError(f"unité inconnue: {unit}")


def relative_surprise(actual: float, forecast: float) -> float:
    """Surprise relative sign-preserving (provisoire, cf. limite #2)."""
    if forecast == 0:
        return actual  # rare; évite division par 0
    return (actual - forecast) / abs(forecast)


# --- IO (réseau / fichier) — non testées unitairement -------------------------


def fetch_fred_series(series_id: str, api_key: str) -> dict[date, float]:
    """Observations FRED -> {date : valeur}. Best-effort : {} si échec."""
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(
                FRED_URL,
                params={
                    "series_id": series_id,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 60,
                },
            )
            r.raise_for_status()
            obs = r.json().get("observations", [])
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        print(f"  ⚠ FRED {series_id} échec: {exc}", file=sys.stderr)
        return {}
    out: dict[date, float] = {}
    for o in obs:
        v = o.get("value")
        if v in (None, ".", ""):
            continue
        try:
            out[date.fromisoformat(o["date"])] = float(v)
        except (ValueError, KeyError):
            continue
    return out


def fetch_binance_klines(interval: str = "1h", limit: int = 1000) -> list[tuple[int, float]]:
    """(open_time_ms, close) triés croissant. Best-effort : [] si échec."""
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(
                BINANCE_KLINES_URL,
                params={"symbol": "BTCUSDT", "interval": interval, "limit": limit},
            )
            r.raise_for_status()
            data = r.json()
        return [(int(k[0]), float(k[4])) for k in data]
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        print(f"  ⚠ fetch Binance échoué: {exc}", file=sys.stderr)
        return []


def price_at(klines: list[tuple[int, float]], times: list[int], ts_ms: int) -> float | None:
    """Close de la kline la plus proche de ts_ms (tolérance PRICE_TOL_MS)."""
    if not klines:
        return None
    i = bisect_right(times, ts_ms)
    best: float | None = None
    best_diff = PRICE_TOL_MS + 1
    for j in (i - 1, i):
        if 0 <= j < len(klines):
            diff = abs(klines[j][0] - ts_ms)
            if diff < best_diff:
                best_diff = diff
                best = klines[j][1]
    return best


def load_latest_forecasts() -> dict[str, dict]:
    """Lit l'archive et renvoie, par event US mappé, le snapshot le plus récent.

    Clé = (title_normalisé + '|' + date FF). Garde le forecast le plus récemment
    archivé (le consensus peut être révisé au fil de la semaine).
    """
    if not SNAPSHOTS_FILE.exists():
        return {}
    best: dict[str, dict] = {}
    with SNAPSHOTS_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                snap = json.loads(line)
            except json.JSONDecodeError:
                continue
            fetched = snap.get("fetched_at") or ""
            for ev in snap.get("events", []):
                if str(ev.get("country")) != "USD":
                    continue
                norm = normalize_title(ev.get("title"))
                if norm not in US_EVENT_MAP:
                    continue
                if parse_macro_value(ev.get("forecast")) is None:
                    continue
                key = f"{norm}|{ev.get('date')}"
                prev = best.get(key)
                if prev is None or fetched >= prev["_fetched"]:
                    best[key] = {**ev, "_norm": norm, "_fetched": fetched}
    return best


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mesure SHADOW de la surprise macro (FF consensus + FRED actual) sur BTC."
    )
    parser.add_argument("--min-pairs", type=int, default=15, help="N min pour un IC non-fragile.")
    args = parser.parse_args()

    print("=" * 76)
    print("  MESURE SHADOW SURPRISE MACRO (ForexFactory + FRED) -> BTC — lecture seule")
    print(f"  {now_utc().isoformat()}")
    print("=" * 76)

    fred_key = get_settings().fred_api_key
    if not fred_key:
        print("\n⚠ Pas de clé FRED (settings.fred_api_key). Impossible de dériver l'actual.")
        return 0

    forecasts = load_latest_forecasts()
    print(f"\nEvents US mappés avec forecast archivé : {len(forecasts)}")
    if not forecasts:
        print("  Aucune donnée. L'archiveur a-t-il tourné ? (cron 2 h)")
        return 0

    now = now_utc()
    klines = fetch_binance_klines()
    times = [k[0] for k in klines]
    print(f"  klines BTC 1h récupérées : {len(klines)}")

    fred_cache: dict[str, dict[date, float]] = {}
    rows = []  # dicts détaillés par event
    n_actual_pending = 0
    # paires (rel_surprise, return) mûres, par horizon
    pairs: dict[int, list[tuple[float, float]]] = {h: [] for h in HORIZONS_H}

    for ev in forecasts.values():
        norm = ev["_norm"]
        series_id, period, unit = US_EVENT_MAP[norm]
        rel = parse_iso(ev.get("date"))
        forecast = parse_macro_value(ev.get("forecast"))
        if rel is None or forecast is None:
            continue
        if series_id not in fred_cache:
            fred_cache[series_id] = fetch_fred_series(series_id, fred_key)
        obs = fred_cache[series_id]
        ref = expected_reference_date(rel, period)
        actual = derive_actual(obs, ref, unit)
        row = {
            "title": ev.get("title"),
            "date": ev.get("date"),
            "impact": ev.get("impact"),
            "forecast": forecast,
            "series": series_id,
            "ref": ref.isoformat(),
            "actual": actual,
        }
        if actual is None:
            n_actual_pending += 1
            rows.append(row)
            continue
        surprise = actual - forecast
        rel_surp = relative_surprise(actual, forecast)
        row["surprise"] = round(surprise, 4)
        row["rel_surprise"] = round(rel_surp, 4)
        # alignement prix : maturité = release + horizon écoulé
        rel_ms = int(rel.timestamp() * 1000)
        p0 = price_at(klines, times, rel_ms)
        if p0 and p0 > 0:
            for h in HORIZONS_H:
                t1 = rel_ms + h * 3600 * 1000
                if datetime.fromtimestamp(t1 / 1000, tz=rel.tzinfo) <= now:
                    p1 = price_at(klines, times, t1)
                    if p1 and p1 > 0:
                        pairs[h].append((rel_surp, p1 / p0 - 1.0))
        rows.append(row)

    # --- rapport par event ---
    print(
        f"\nEvents avec actual FRED disponible : {sum(1 for r in rows if r.get('actual') is not None)}"
    )
    print(f"Events avec actual PENDING (FRED pas encore publié) : {n_actual_pending}")
    print("\n--- Détail par event (consensus archivé + actual FRED dérivé) ---")
    for r in sorted(rows, key=lambda x: x["date"]):
        if r.get("actual") is None:
            print(
                f"  [{r['impact']:>6}] {r['title']:<34} fc={r['forecast']:<7} "
                f"actual=PENDING (FRED {r['series']} ref {r['ref']})"
            )
        else:
            print(
                f"  [{r['impact']:>6}] {r['title']:<34} fc={r['forecast']:<7} "
                f"actual={r['actual']:<8.3f} surprise={r['surprise']:+.3f} "
                f"(rel {r['rel_surprise']:+.3f})"
            )

    # --- IC par horizon ---
    print("\n--- Valeur prédictive sur BTC (PRÉLIMINAIRE) ---")
    any_mature = False
    for h in HORIZONS_H:
        ps = pairs[h]
        if not ps:
            print(f"  +{h:>2}h : 0 paire mûre.")
            continue
        any_mature = True
        sig = [p[0] for p in ps]
        ret = [p[1] for p in ps]
        ic = spearman_correlation(sig, ret)
        directional = [(s, rr) for s, rr in ps if abs(s) > 1e-9]
        if directional:
            hits = sum(1 for s, rr in directional if (s > 0) == (rr > 0))
            hit_rate = hits / len(directional) * 100
            gain = sum((rr if s > 0 else -rr) for s, rr in directional) / len(directional) * 100
        else:
            hit_rate = gain = float("nan")
        ic_s = "n/a" if ic is None else f"{ic:+.3f}"
        print(
            f"  +{h:>2}h : N={len(ps):<3} IC={ic_s:<7} "
            f"hit-signe={hit_rate:4.1f}% gain-en-suivant={gain:+.3f}%"
        )

    print("\n--- VERDICT ---")
    if not any_mature:
        print("  Aucune paire (surprise, rendement) mûre : events trop récents et/ou")
        print("  actuals FRED pas encore publiés. C'est ATTENDU au démarrage.")
    max_n = max((len(pairs[h]) for h in HORIZONS_H), default=0)
    if max_n < args.min_pairs:
        print(f"  ⚠ N max={max_n} < {args.min_pairs} → NON CONCLUANT (échantillon trop faible).")
    print("  ⚠ Surprise relative poolée cross-event = normalisation v1 (cf. limite #2).")
    print("  → Re-lancer après ≥ 2 semaines (idéalement NFP + CPI + FOMC). AUCUN enrôlement.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
