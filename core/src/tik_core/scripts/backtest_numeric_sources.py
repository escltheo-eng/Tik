"""Backtest empirique des paliers des sources numériques (P2 plan stratégique fiabilité).

Pour chaque source numérique (FG, GDELT tone, DXY, CFTC COT) :
1. Récupère l'historique 12m via les helpers `fetch_numeric_history`
2. Pour chaque date dans l'historique, calcule le bias selon les paliers
   actuels de `swing_engine.py` (importés directement pour cohérence)
3. Récupère le delta de prix de l'asset cible (BTC ou GOLD) à 24h, 5j, 30j
4. Calcule 3 métriques : hit rate par palier, IC Spearman, hit rate cas extrêmes
5. Génère rapport JSON + Markdown avec recommandations chiffrées

Cohérent avec le pattern `backtest.py` et `backtest_golden.py` (script CLI,
sortie JSON Lines + rapport MD).

Usage:
    python -m tik_core.scripts.backtest_numeric_sources \\
        --days-back 365 \\
        --output-json core/data/numeric_calibration/report.json \\
        --output-md core/data/numeric_calibration/report.md \\
        [--fred-api-key KEY]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog

from tik_core.config import get_settings
from tik_core.scoring.swing_engine import (
    _compute_cot_bias,
    _compute_dxy_bias,
    _compute_fg_bias,
    _compute_gdelt_bias,
)
from tik_core.scripts.backtest import (
    fetch_btc_history,
    fetch_gold_history,
    find_closest_price,
)
from tik_core.scripts.fetch_numeric_history import (
    fetch_cot_history,
    fetch_dxy_history,
    fetch_fear_greed_history,
    fetch_gdelt_tone_history,
)

log = structlog.get_logger()

# Seuils directionnalité par horizon (cohérent macro Paquet 17 P5)
DIRECTIONALITY_THRESHOLDS_PCT: dict[int, float] = {
    24: 0.5,  # 24h
    120: 1.0,  # 5j (5 × 24h)
    720: 2.0,  # 30j
}

# Tolérance find_closest_price : 24h pour daily klines, 48h pour weekly COT
PRICE_MATCH_TOLERANCE_MS = 24 * 3600 * 1000

# Seuil IC Spearman pour drapeau dans le rapport
IC_SIGNIFICANCE_THRESHOLD = 0.10  # |IC| > 0.1 = signal exploitable
IC_STRONG_THRESHOLD = 0.20

# Seuils hit rate
HIT_RATE_GOOD = 0.55  # > 55 % = signal exploitable
HIT_RATE_EXCELLENT = 0.65


def parse_horizons(raw: str) -> list[int]:
    """Parse '24h,5d,30d' → [24, 120, 720] heures."""
    horizons_h: list[int] = []
    for token in raw.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token.endswith("h"):
            horizons_h.append(int(token[:-1]))
        elif token.endswith("d"):
            horizons_h.append(int(token[:-1]) * 24)
        else:
            raise ValueError(f"Horizon format inconnu: {token!r} (attendu 24h, 5d, ...)")
    return horizons_h


def parse_iso_date(date_str: str) -> datetime:
    """Parse YYYY-MM-DD ou ISO datetime → datetime UTC à 00:00."""
    if "T" in date_str:
        # Strip tz info, garde la date
        date_str = date_str.split("T")[0]
    return datetime.fromisoformat(date_str).replace(tzinfo=UTC)


def is_success(direction: str, bias: float, delta_pct: float, threshold_pct: float) -> bool | None:  # noqa: ARG001 — direction conservé pour la symétrie d'interface
    """Détermine si le delta de prix confirme le bias contrarian/trend.

    - direction='contrarian': bias > 0 → on attend bull (delta > +threshold)
                              bias < 0 → on attend bear (delta < -threshold)
                              bias = 0 → cas neutral, retourne None (pas évaluable)
    - direction='trend':      bias > 0 → on attend bull
                              etc.

    En contrarian, le bias EST DÉJÀ inversé par `_compute_X_bias`. Donc bias > 0
    signifie déjà "on attend une hausse de l'asset". Pas d'inversion supplémentaire.
    """
    if bias == 0.0:
        return None  # palier neutral, pas évaluable directionnellement
    if abs(delta_pct) < threshold_pct:
        return False  # mouvement insuffisant pour confirmer
    expected_up = bias > 0
    actual_up = delta_pct > 0
    return expected_up == actual_up


def spearman_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Coefficient de corrélation de rang de Spearman (sans scipy).

    Spearman = Pearson sur les rangs. Implémentation maison ~25 lignes.
    Retourne None si < 5 points ou variance nulle.
    """
    if len(xs) != len(ys) or len(xs) < 5:
        return None
    rx = _ranks(xs)
    ry = _ranks(ys)
    n = len(rx)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n)) / n
    var_x = sum((r - mx) ** 2 for r in rx) / n
    var_y = sum((r - my) ** 2 for r in ry) / n
    if var_x == 0 or var_y == 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def _ranks(values: list[float]) -> list[float]:
    """Rangs avec gestion ex-aequo (rang moyen)."""
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks: list[float] = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1  # rang 1-indexed, moyen pour les ex-aequo
        for k in range(i, j + 1):
            original_idx = indexed[k][0]
            ranks[original_idx] = avg_rank
        i = j + 1
    return ranks


def evaluate_source_simple(
    source_history: list[dict[str, Any]],
    price_history: list[tuple[int, float]],
    asset: str,
    compute_bias: Callable[[Any], tuple[float, str]],
    direction: str,
    horizons_h: list[int],
) -> dict[str, Any]:
    """Évalue une source dont le bias est calculé point-par-point (FG, GDELT, COT)."""
    rows: list[dict[str, Any]] = []
    for point in source_history:
        try:
            value = point["value"]
            date_str = point["date"]
        except (KeyError, TypeError):
            continue

        # Cast value selon le type attendu par compute_bias
        try:
            cast_value = int(value) if compute_bias is _compute_fg_bias else float(value)
        except (TypeError, ValueError):
            continue

        try:
            bias, palier = compute_bias(cast_value)
        except Exception as exc:  # noqa: BLE001
            log.warning("evaluate.compute_bias_error", error=str(exc), value=value)
            continue

        target_dt = parse_iso_date(date_str)
        entry_price = find_closest_price(
            price_history, target_dt, max_diff_ms=PRICE_MATCH_TOLERANCE_MS
        )
        if entry_price is None:
            continue

        deltas: dict[int, float] = {}
        for h in horizons_h:
            future_dt = target_dt + timedelta(hours=h)
            if future_dt > datetime.now(tz=UTC):
                continue  # horizon dans le futur
            future_price = find_closest_price(
                price_history, future_dt, max_diff_ms=PRICE_MATCH_TOLERANCE_MS
            )
            if future_price is None:
                continue
            deltas[h] = (future_price - entry_price) / entry_price * 100

        if not deltas:
            continue

        rows.append(
            {
                "date": date_str,
                "value": value,
                "bias": bias,
                "palier": palier,
                "entry_price": entry_price,
                "deltas_pct": deltas,
            }
        )

    return _analyze_rows(rows, direction, horizons_h, asset)


def evaluate_source_dxy(
    dxy_history: list[dict[str, Any]],
    price_history: list[tuple[int, float]],
    horizons_h: list[int],
) -> dict[str, Any]:
    """Cas spécial DXY : bias calculé sur variation 5d, donc on slice l'historique."""
    rows: list[dict[str, Any]] = []
    for i, point in enumerate(dxy_history):
        if i < 5:
            continue  # besoin de 5 points historiques
        # _compute_dxy_bias attend desc (le plus récent en premier)
        slice_asc = dxy_history[max(0, i - 9) : i + 1]
        slice_desc = list(reversed(slice_asc))
        result = _compute_dxy_bias(slice_desc)
        if result is None:
            continue
        bias, palier, recent, past = result

        date_str = point["date"]
        target_dt = parse_iso_date(date_str)
        entry_price = find_closest_price(
            price_history, target_dt, max_diff_ms=PRICE_MATCH_TOLERANCE_MS
        )
        if entry_price is None:
            continue

        deltas: dict[int, float] = {}
        for h in horizons_h:
            future_dt = target_dt + timedelta(hours=h)
            if future_dt > datetime.now(tz=UTC):
                continue
            future_price = find_closest_price(
                price_history, future_dt, max_diff_ms=PRICE_MATCH_TOLERANCE_MS
            )
            if future_price is None:
                continue
            deltas[h] = (future_price - entry_price) / entry_price * 100

        if not deltas:
            continue

        rows.append(
            {
                "date": date_str,
                "value": (recent - past) / past * 100,  # variation 5d %
                "bias": bias,
                "palier": palier,
                "entry_price": entry_price,
                "deltas_pct": deltas,
            }
        )

    return _analyze_rows(rows, "contrarian", horizons_h, "GOLD")


def _analyze_rows(
    rows: list[dict[str, Any]],
    direction: str,
    horizons_h: list[int],
    asset: str,
) -> dict[str, Any]:
    """Calcule les 3 métriques (hit rate par palier, IC Spearman, hit rate extrêmes)."""
    n_total = len(rows)
    if n_total == 0:
        return {
            "n_total": 0,
            "asset": asset,
            "direction": direction,
            "metrics_by_horizon": {},
            "warning": "Aucun point évaluable",
        }

    metrics_by_horizon: dict[str, Any] = {}

    for h in horizons_h:
        threshold = DIRECTIONALITY_THRESHOLDS_PCT.get(h, 1.0)

        # Hit rate par palier
        by_palier: dict[str, dict[str, Any]] = {}
        ic_pairs_value: list[float] = []
        ic_pairs_delta: list[float] = []
        extreme_rows: list[dict[str, Any]] = []  # |bias| == 1.0

        for row in rows:
            if h not in row["deltas_pct"]:
                continue
            delta_pct = row["deltas_pct"][h]
            palier = row["palier"]
            bias = row["bias"]
            value = row["value"]

            entry = by_palier.setdefault(
                palier, {"n": 0, "n_success": 0, "n_evaluable": 0, "delta_avg": 0.0, "biases": []}
            )
            entry["n"] += 1
            entry["delta_avg"] += delta_pct
            entry["biases"].append(bias)

            success = is_success(direction, bias, delta_pct, threshold)
            if success is not None:  # palier non-neutral
                entry["n_evaluable"] += 1
                if success:
                    entry["n_success"] += 1

            ic_pairs_value.append(float(value))
            ic_pairs_delta.append(delta_pct)

            if abs(bias) == 1.0:
                extreme_rows.append({"bias": bias, "delta_pct": delta_pct, "success": success})

        # Finalize palier metrics
        finalized_paliers: dict[str, Any] = {}
        for palier, entry in by_palier.items():
            n = entry["n"]
            evaluable = entry["n_evaluable"]
            hit_rate = entry["n_success"] / evaluable if evaluable > 0 else None
            finalized_paliers[palier] = {
                "n": n,
                "n_evaluable": evaluable,
                "n_success": entry["n_success"],
                "hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
                "delta_avg_pct": round(entry["delta_avg"] / n, 4),
                "bias_value": entry["biases"][0] if entry["biases"] else None,
            }

        # IC Spearman
        ic = spearman_correlation(ic_pairs_value, ic_pairs_delta)
        ic_expected_sign = "negative" if direction == "contrarian" else "positive"

        # Hit rate cas extrêmes
        n_extreme_evaluable = sum(1 for r in extreme_rows if r["success"] is not None)
        n_extreme_success = sum(1 for r in extreme_rows if r["success"] is True)
        extreme_hit_rate = (
            n_extreme_success / n_extreme_evaluable if n_extreme_evaluable > 0 else None
        )

        metrics_by_horizon[f"{h}h"] = {
            "threshold_pct": threshold,
            "n_evaluable_total": sum(p["n_evaluable"] for p in finalized_paliers.values()),
            "by_palier": finalized_paliers,
            "ic_spearman": round(ic, 4) if ic is not None else None,
            "ic_expected_sign": ic_expected_sign,
            "ic_actual_sign": "positive"
            if (ic is not None and ic > 0)
            else "negative"
            if (ic is not None and ic < 0)
            else None,
            "ic_sign_correct": (None if ic is None else (ic < 0) == (direction == "contrarian")),
            "extreme": {
                "n_total": len(extreme_rows),
                "n_evaluable": n_extreme_evaluable,
                "n_success": n_extreme_success,
                "hit_rate": round(extreme_hit_rate, 4) if extreme_hit_rate is not None else None,
            },
        }

    return {
        "n_total": n_total,
        "asset": asset,
        "direction": direction,
        "metrics_by_horizon": metrics_by_horizon,
    }


def build_recommendations(report: dict[str, Any]) -> list[str]:
    """Génère recommandations chiffrées à partir des métriques calculées."""
    recos: list[str] = []
    for source_name, source_data in report["by_source"].items():
        if source_data["n_total"] == 0:
            recos.append(
                f"⚠ **{source_name}** : aucun point évaluable, vérifier la source de données."
            )
            continue

        for horizon, metrics in source_data["metrics_by_horizon"].items():
            ic = metrics.get("ic_spearman")
            ic_correct = metrics.get("ic_sign_correct")
            extreme = metrics.get("extreme", {})

            # Drapeau IC sign
            if ic is not None and ic_correct is False:
                recos.append(
                    f"🔴 **{source_name} @ {horizon}** : IC Spearman = {ic:+.4f} "
                    f"(signe opposé à `{metrics['ic_expected_sign']}` attendu pour `{source_data['direction']}`). "
                    f"Sémantique de l'overlay à reconsidérer."
                )

            # Drapeau IC magnitude
            if ic is not None and abs(ic) < IC_SIGNIFICANCE_THRESHOLD:
                recos.append(
                    f"⚠ **{source_name} @ {horizon}** : IC = {ic:+.4f} (|IC| < {IC_SIGNIFICANCE_THRESHOLD}) "
                    f"→ source non significative à cet horizon."
                )
            elif ic is not None and abs(ic) >= IC_STRONG_THRESHOLD:
                recos.append(
                    f"✅ **{source_name} @ {horizon}** : IC = {ic:+.4f} (|IC| ≥ {IC_STRONG_THRESHOLD}) "
                    f"→ signal **fort**, garder le mapping actuel."
                )

            # Drapeau cas extrêmes
            if extreme.get("hit_rate") is not None:
                hr_extreme = extreme["hit_rate"]
                n_eval = extreme.get("n_evaluable", 0)
                if hr_extreme >= HIT_RATE_EXCELLENT and n_eval >= 10:
                    recos.append(
                        f"✅ **{source_name} @ {horizon}** : paliers extrêmes (|bias|=1.0) hit rate "
                        f"= {hr_extreme:.1%} (n={n_eval}) → **conserver les paliers actuels**."
                    )
                elif hr_extreme < 0.45 and n_eval >= 10:
                    recos.append(
                        f"🔴 **{source_name} @ {horizon}** : paliers extrêmes hit rate "
                        f"= {hr_extreme:.1%} (n={n_eval}, < 45 %) → **paliers à élargir** (seuils extrêmes trop laxistes)."
                    )

            # Hit rate par palier : flag les paliers ±1.0 vs ±0.5
            paliers = metrics.get("by_palier", {})
            for palier_name, palier_data in paliers.items():
                hr = palier_data.get("hit_rate")
                n_eval = palier_data.get("n_evaluable", 0)
                if hr is None or n_eval < 10:
                    continue
                bias_val = palier_data.get("bias_value")
                if bias_val == 0.0:
                    continue
                if abs(bias_val) == 0.5 and hr >= HIT_RATE_GOOD:
                    recos.append(
                        f"✅ **{source_name} @ {horizon}**, palier `{palier_name}` (bias=±0.5) : "
                        f"hit rate = {hr:.1%} (n={n_eval}) → **palier moyen utile**."
                    )

    if not recos:
        recos.append(
            "ℹ Aucune action urgente — tous les paliers et IC restent dans la zone acceptable."
        )
    return recos


def render_markdown(report: dict[str, Any]) -> str:
    """Rapport Markdown lisible humain."""
    lines: list[str] = []
    args = report["meta"]
    lines.append("# Backtest empirique paliers sources numériques (P2)")
    lines.append("")
    lines.append(f"**Date du run** : {args['ran_at']}")
    lines.append(f"**Période** : {args['days_back']} jours (depuis {args['since_date']})")
    lines.append(f"**Horizons mesurés** : {', '.join(args['horizons'])}")
    lines.append("**Seuils directionnalité** : 24h=0.5 % / 5j=1.0 % / 30j=2.0 %")
    lines.append("")
    lines.append("## Résumé")
    lines.append("")

    # Tableau résumé
    lines.append(
        "| Source | Asset | Direction | n total | IC max (|.|) | Cas extrême max hit rate |"
    )
    lines.append("|---|---|---|---|---|---|")
    for source_name, source_data in report["by_source"].items():
        ic_max = 0.0
        ic_max_horizon = "-"
        extreme_max = 0.0
        extreme_max_horizon = "-"
        for h, m in source_data["metrics_by_horizon"].items():
            if m.get("ic_spearman") is not None and abs(m["ic_spearman"]) > ic_max:
                ic_max = abs(m["ic_spearman"])
                ic_max_horizon = h
            extreme_hr = m.get("extreme", {}).get("hit_rate")
            if extreme_hr is not None and extreme_hr > extreme_max:
                extreme_max = extreme_hr
                extreme_max_horizon = h

        ic_str = f"{ic_max:.4f} ({ic_max_horizon})" if ic_max > 0 else "-"
        extreme_str = f"{extreme_max:.1%} ({extreme_max_horizon})" if extreme_max > 0 else "-"
        lines.append(
            f"| **{source_name}** | {source_data['asset']} | {source_data['direction']} | "
            f"{source_data['n_total']} | {ic_str} | {extreme_str} |"
        )

    lines.append("")
    lines.append("## Recommandations chiffrées")
    lines.append("")
    for reco in report["recommendations"]:
        lines.append(f"- {reco}")

    lines.append("")
    lines.append("## Détail par source × horizon")
    lines.append("")

    for source_name, source_data in report["by_source"].items():
        lines.append(
            f"### {source_name} (asset={source_data['asset']}, direction={source_data['direction']})"
        )
        lines.append("")
        if source_data["n_total"] == 0:
            lines.append("Aucun point évaluable.")
            lines.append("")
            continue
        lines.append(f"**n total** : {source_data['n_total']}")
        lines.append("")

        for horizon, metrics in source_data["metrics_by_horizon"].items():
            lines.append(f"#### Horizon {horizon}")
            lines.append("")
            ic = metrics.get("ic_spearman")
            ic_str = f"{ic:+.4f}" if ic is not None else "n/a"
            lines.append(f"- **IC Spearman** : {ic_str} (attendu : {metrics['ic_expected_sign']})")
            extreme = metrics.get("extreme", {})
            extreme_hr = extreme.get("hit_rate")
            extreme_hr_str = f"{extreme_hr:.1%}" if extreme_hr is not None else "n/a"
            lines.append(
                f"- **Cas extrêmes (|bias|=1.0)** : hit rate = {extreme_hr_str} "
                f"(n={extreme.get('n_evaluable', 0)} sur {extreme.get('n_total', 0)} extrêmes)"
            )
            lines.append("")
            lines.append("**Hit rate par palier** :")
            lines.append("")
            lines.append("| Palier | bias | n | n_evaluable | hit_rate | delta_avg_pct |")
            lines.append("|---|---|---|---|---|---|")
            for palier_name, p in sorted(metrics["by_palier"].items()):
                hr = p.get("hit_rate")
                hr_str = f"{hr:.1%}" if hr is not None else "neutral"
                lines.append(
                    f"| {palier_name} | {p['bias_value']:+.1f} | {p['n']} | "
                    f"{p['n_evaluable']} | {hr_str} | {p['delta_avg_pct']:+.4f} |"
                )
            lines.append("")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Limites assumées")
    lines.append("")
    lines.append(
        "- **Période 12m strongly bullish (2025-2026)** : régime haussier crypto + or. Reco issues ne couvriront pas un régime bear (à reproduire dans 6-12 mois)."
    )
    lines.append(
        "- **COT hebdomadaire** = ~52 points/12m. IC Spearman bruité, à interpréter prudemment."
    )
    lines.append(
        "- **Direction contrarian assumée pour les 4 sources** : le drapeau `🔴 IC sign opposé` signale une remise en question potentielle de la sémantique."
    )
    lines.append(
        "- **Pas de prise en compte régime de marché** (bull/bear/range). Calibration globale sur 12m."
    )
    lines.append("")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest paliers sources numériques (P2)")
    parser.add_argument("--days-back", type=int, default=365)
    parser.add_argument("--horizons", default="24h,5d,30d")
    parser.add_argument(
        "--output-json",
        default="core/data/numeric_calibration/numeric_calibration_report.json",
    )
    parser.add_argument(
        "--output-md",
        default="core/data/numeric_calibration/numeric_calibration_report.md",
    )
    parser.add_argument(
        "--fred-api-key", default=None, help="Si non fourni, lit settings.fred_api_key (.env)"
    )
    parser.add_argument("--gdelt-query", default="gold price")
    args = parser.parse_args()

    horizons_h = parse_horizons(args.horizons)
    fred_key = (
        args.fred_api_key or os.environ.get("FRED_API_KEY") or get_settings().fred_api_key or ""
    )
    log.info(
        "backtest_numeric.start",
        days_back=args.days_back,
        horizons=horizons_h,
        fred_key_set=bool(fred_key),
    )

    # Fetch toutes les histoires en parallèle
    async with httpx.AsyncClient(timeout=60.0) as client:
        log.info("backtest_numeric.fetch.sources_start")
        fg_history, gdelt_history, dxy_history, cot_history = await asyncio.gather(
            fetch_fear_greed_history(args.days_back, client=client),
            fetch_gdelt_tone_history(
                query=args.gdelt_query, days_back=args.days_back, client=client
            ),
            fetch_dxy_history(api_key=fred_key, days_back=args.days_back, client=client),
            fetch_cot_history(args.days_back, client=client),
        )
        log.info(
            "backtest_numeric.fetch.sources_done",
            fg=len(fg_history),
            gdelt=len(gdelt_history),
            dxy=len(dxy_history),
            cot=len(cot_history),
        )

        # Fetch prix BTC et GOLD (avec buffer pour horizons longs)
        log.info("backtest_numeric.fetch.prices_start")
        btc_history = await fetch_btc_history(client, interval="1d", limit=400)
        gold_history = await fetch_gold_history(client, interval="1d", range_param="2y")
        log.info(
            "backtest_numeric.fetch.prices_done",
            btc=len(btc_history),
            gold=len(gold_history),
        )

    # Évaluer les 4 sources
    log.info("backtest_numeric.evaluate.start")
    by_source = {
        "fear_greed": evaluate_source_simple(
            fg_history, btc_history, "BTC", _compute_fg_bias, "contrarian", horizons_h
        ),
        "gdelt_tone": evaluate_source_simple(
            gdelt_history, gold_history, "GOLD", _compute_gdelt_bias, "contrarian", horizons_h
        ),
        "dxy": evaluate_source_dxy(dxy_history, gold_history, horizons_h),
        "cftc_cot": evaluate_source_simple(
            cot_history, gold_history, "GOLD", _compute_cot_bias, "contrarian", horizons_h
        ),
    }

    now = datetime.now(tz=UTC)
    since = now - timedelta(days=args.days_back)
    report = {
        "meta": {
            "ran_at": now.isoformat(),
            "days_back": args.days_back,
            "since_date": since.date().isoformat(),
            "horizons": [f"{h}h" for h in horizons_h],
            "thresholds_directionality": {
                f"{h}h": DIRECTIONALITY_THRESHOLDS_PCT.get(h, 1.0) for h in horizons_h
            },
            "n_history_fetched": {
                "fear_greed": len(fg_history),
                "gdelt_tone": len(gdelt_history),
                "dxy": len(dxy_history),
                "cftc_cot": len(cot_history),
                "btc_klines": len(btc_history),
                "gold_klines": len(gold_history),
            },
        },
        "by_source": by_source,
    }
    report["recommendations"] = build_recommendations(report)

    # Écriture sorties
    out_json = Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    log.info("backtest_numeric.json_written", path=str(out_json))

    out_md = Path(args.output_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_markdown(report), encoding="utf-8")
    log.info("backtest_numeric.md_written", path=str(out_md))

    # Print résumé console
    print("\n=== Backtest paliers sources numériques (P2) ===")
    print(f"Période : {args.days_back} j ({since.date().isoformat()} → aujourd'hui)")
    print(f"Horizons : {', '.join(report['meta']['horizons'])}")
    print("\nPoints récupérés :")
    for k, v in report["meta"]["n_history_fetched"].items():
        print(f"  - {k}: {v}")
    print("\nÉvaluation par source :")
    for source_name, source_data in by_source.items():
        print(f"  - {source_name}: n_total={source_data['n_total']}, asset={source_data['asset']}")
    print(f"\nRecommandations ({len(report['recommendations'])}):")
    for r in report["recommendations"][:10]:
        print(f"  {r}")
    if len(report["recommendations"]) > 10:
        print(f"  ... ({len(report['recommendations']) - 10} autres dans le rapport MD)")
    print("\nRapports écrits :")
    print(f"  - JSON : {out_json}")
    print(f"  - MD : {out_md}")


if __name__ == "__main__":
    asyncio.run(main())
