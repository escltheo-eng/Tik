"""Mesure : PAXG (Binance) suit-il assez bien GC=F (Yahoo) pour justifier un flash GOLD ?

Contexte (ADR-005 + question 2026-06-26) : le flash GOLD est bloqué parce que la
source de prix GOLD (Yahoo `GC=F`) a 15 min de délai, incompatible avec la
fraîcheur < 60 s du flash. Binance cote **PAXG** (PAX Gold, token adossé à l'or
physique, ~1 once) en temps réel 24/7 → ça *pourrait* lever le verrou. MAIS PAXG
est un PROXY (premium/discount, liquidité, horaires crypto) : avant de câbler
quoi que ce soit, on MESURE s'il suit `GC=F`.

Ce script est une MESURE SHADOW pure (lecture seule, n'influence aucun moteur).
Il backfille ~40 j de klines 1h des deux sources, les aligne sur les horodatages
communs (l'or ne cote pas la nuit/week-end, PAXG si → on prend l'intersection,
comme le piège résolu d'ADR-032), et calcule :
  - corrélation de Pearson des rendements horaires alignés (suivi directionnel),
  - tracking error (écart-type des différences de rendement) + RMSE,
  - premium PAXG vs GC=F (niveau) et sa stabilité.

⚠ Honnêteté (Axe #1) : un bon suivi 1h est NÉCESSAIRE mais PAS SUFFISANT pour le
flash (horizon minutes — Yahoo ne fournit pas d'intraday fin fiable sur GC=F pour
le mesurer ici). Et même un suivi parfait ne prouve AUCUN edge : il lève juste le
verrou « source de prix ». GOLD reste non tradé avec Tik (hit 4.8 %, Garde-fou
2-bis). Ce script répond seulement à : « PAXG est-il un proxy GOLD assez fidèle
pour qu'un flash GOLD ait un sens technique ? ».

Usage (dans le conteneur core, qui a httpx) :
    docker compose exec core python -m tik_core.scripts.measure_paxg_gold_tracking
"""

from __future__ import annotations

import math
import statistics

import httpx

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
# UA réaliste : Yahoo 429 parfois sans en-tête navigateur.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/537.36"


def _hour_bucket(epoch_seconds: float) -> int:
    """Plancher à l'heure pleine (UTC) pour aligner Binance et Yahoo."""
    return int(epoch_seconds // 3600 * 3600)


def fetch_paxg_1h() -> dict[int, float]:
    """Klines PAXGUSDT 1h Binance (≤ 1000 ≈ 41 j). Retourne {heure_epoch: close}."""
    resp = httpx.get(
        BINANCE_KLINES,
        params={"symbol": "PAXGUSDT", "interval": "1h", "limit": 1000},
        timeout=30.0,
    )
    resp.raise_for_status()
    out: dict[int, float] = {}
    for row in resp.json():
        # row[0] = openTime (ms), row[4] = close (str)
        out[_hour_bucket(row[0] / 1000.0)] = float(row[4])
    return out


def fetch_gold_1h() -> dict[int, float]:
    """Klines GC=F 1h Yahoo (~3 mois). Retourne {heure_epoch: close}."""
    resp = httpx.get(
        YAHOO_CHART,
        params={"interval": "1h", "range": "3mo"},
        headers={"User-Agent": UA},
        timeout=30.0,
    )
    resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    out: dict[int, float] = {}
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue  # trou de marché (gap) → on saute
        out[_hour_bucket(ts)] = float(close)
    return out


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Corrélation de Pearson (stdlib, sans numpy). None si variance nulle."""
    n = len(xs)
    if n < 3:
        return None
    mx = statistics.fmean(xs)
    my = statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def main() -> None:
    print("Mesure PAXG (Binance) vs GC=F (Yahoo) — suivi pour un éventuel flash GOLD\n")
    try:
        paxg = fetch_paxg_1h()
    except Exception as exc:  # noqa: BLE001
        print(f"ERREUR fetch Binance PAXGUSDT : {exc}")
        print("→ Vérifier que PAXGUSDT est toujours listé/liquide sur Binance.")
        return
    try:
        gold = fetch_gold_1h()
    except Exception as exc:  # noqa: BLE001
        print(f"ERREUR fetch Yahoo GC=F : {exc}")
        return

    common = sorted(set(paxg) & set(gold))
    print(f"Heures PAXG: {len(paxg)} · GC=F: {len(gold)} · communes alignées: {len(common)}")
    if len(common) < 30:
        print("→ Trop peu d'heures communes pour conclure (besoin ≥ 30). Stop.")
        return

    span_days = (common[-1] - common[0]) / 86400.0
    print(f"Fenêtre commune: {span_days:.1f} jours\n")

    # Premium de niveau : PAXG/GC=F - 1 (les deux sont en USD/once → comparables).
    premiums = [(paxg[t] / gold[t] - 1.0) * 100 for t in common]
    print(f"Premium PAXG vs GC=F : moy {statistics.fmean(premiums):+.2f}% "
          f"(min {min(premiums):+.2f}% / max {max(premiums):+.2f}% / "
          f"écart-type {statistics.pstdev(premiums):.2f} pts)")

    # Rendements sur intervalles communs CONSÉCUTIFS (robuste aux gaps : on
    # compare le même intervalle pour les deux séries).
    ret_paxg: list[float] = []
    ret_gold: list[float] = []
    for a, b in zip(common, common[1:]):
        ret_paxg.append(paxg[b] / paxg[a] - 1.0)
        ret_gold.append(gold[b] / gold[a] - 1.0)

    r = pearson(ret_paxg, ret_gold)
    diffs = [p - g for p, g in zip(ret_paxg, ret_gold)]
    tracking_err = statistics.pstdev(diffs) * 100  # en %
    rmse = math.sqrt(statistics.fmean([d * d for d in diffs])) * 100

    print(f"\nN rendements appariés : {len(ret_paxg)}")
    print(f"Corrélation de Pearson (rendements horaires alignés) : "
          f"{r:.3f}" if r is not None else "Corrélation : indéfinie")
    print(f"Tracking error (σ des écarts de rendement) : {tracking_err:.3f} %/h")
    print(f"RMSE des écarts de rendement                : {rmse:.3f} %/h")

    # Verdict gradué (suivi technique uniquement — PAS un verdict d'edge).
    print("\n--- VERDICT (suivi technique, pas un edge) ---")
    if r is None:
        print("Indéfini (variance nulle).")
    elif r >= 0.90 and tracking_err < 0.10:
        print("✅ PAXG suit TRÈS bien GC=F → le verrou « source de prix » du flash GOLD "
              "tombe. Reste à prouver un EDGE (mesure shadow d'un flash PAXG vs baseline) "
              "AVANT de câbler. Et garder en tête : overlays flash = carnet crypto PAXG.")
    elif r >= 0.80:
        print("🟠 PAXG suit CORRECTEMENT GC=F mais avec du bruit (proxy crypto). Un flash "
              "GOLD sur PAXG mesurerait un instrument partiellement différent du swing GOLD "
              "(GC=F). Faisable techniquement, mais l'incohérence + l'absence d'edge GOLD "
              "rendent le chantier peu prioritaire (Axe #1).")
    else:
        print("❌ PAXG ne suit PAS assez GC=F (corrélation faible). Un flash GOLD sur PAXG "
              "refléterait la dynamique crypto, pas l'or → à NE PAS construire.")

    print("\nRappels honnêtes : (1) 1h ≠ flash (minutes) — suivi fin non mesuré ici ; "
          "(2) bon suivi ≠ edge ; (3) GOLD non tradé avec Tik (Garde-fou 2-bis).")


if __name__ == "__main__":
    main()
