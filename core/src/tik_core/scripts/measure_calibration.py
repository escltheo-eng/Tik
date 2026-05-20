"""Mesure de calibration sur le golden dataset Tik (Paquet 4 Session 4).

Joint 4 sources de données par `id` stable :
- raw_items.jsonl       (items collectés)
- annotations.jsonl     (verdict humain blinded)
- predictions.jsonl     (verdicts Ollama + keywords)
- prices.jsonl          (delta % multi-horizon vs marché réel)

Et calcule 3 familles de métriques :

1. **Concordance humain ↔ classifier**
   - Accuracy par classifier (proportion de fois où il est d'accord avec l'humain)
   - Confusion matrix (où ils divergent)

2. **Calibration vs marché réel** (la vérité de référence absolue)
   - Hit rate par classifier (prediction correcte = mouvement de marché conforme)
   - Comparaison vs baselines (random, always bull/bear/neutral)

3. **Per-source**
   - Quelle source (Google News / CryptoCompare / Reddit) est la plus prédictive ?
   - Doit-on ajuster `SOURCE_SCORES` en conséquence ?

Génère deux fichiers :
- calibration_report.json (machine-readable, pour automation future)
- calibration_report.md (human-readable, à inclure dans methodology/calibration.md)

Usage:
    docker compose exec core python -m tik_core.scripts.measure_calibration
    docker compose exec core python -m tik_core.scripts.measure_calibration \
        --horizon 5d --threshold 0.5
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

DATA_DIR = Path("/app/data/golden_dataset")
RAW_ITEMS_FILE = DATA_DIR / "raw_items.jsonl"
ANNOTATIONS_FILE = DATA_DIR / "annotations.jsonl"
PREDICTIONS_FILE = DATA_DIR / "predictions.jsonl"
PRICES_FILE = DATA_DIR / "prices.jsonl"
REPORT_JSON_FILE = DATA_DIR / "calibration_report.json"
REPORT_MD_FILE = DATA_DIR / "calibration_report.md"

VERDICTS = ("bull", "bear", "neutral")


# === Chargement ===


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _index_by_id(records: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in records if "id" in r}


# === Helpers de scoring ===


def _verdict_correct_vs_market(verdict: str, delta_pct: float, threshold: float) -> bool:
    """Un verdict est 'correct' si le delta marché va dans le bon sens."""
    if verdict == "bull":
        return delta_pct > threshold
    if verdict == "bear":
        return delta_pct < -threshold
    if verdict == "neutral":
        return abs(delta_pct) < threshold
    return False


def _confusion_key(predicted: str | None, reference: str | None) -> tuple[str, str]:
    """Couple (predicted, reference) avec normalisation des None en 'n/a'."""
    return (predicted or "n/a", reference or "n/a")


# === Métriques ===


def _accuracy(records: list[dict], pred_key: str, ref_key: str) -> float | None:
    """Proportion de records où predicted == reference (ignore None)."""
    eligible = [r for r in records if r.get(pred_key) is not None and r.get(ref_key) is not None]
    if not eligible:
        return None
    n_match = sum(1 for r in eligible if r[pred_key] == r[ref_key])
    return n_match / len(eligible)


def _confusion_matrix(
    records: list[dict], pred_key: str, ref_key: str
) -> dict[str, dict[str, int]]:
    """Matrice {predicted: {reference: count}}."""
    matrix: dict[str, dict[str, int]] = {}
    for v_pred in (*VERDICTS, "n/a"):
        matrix[v_pred] = dict.fromkeys((*VERDICTS, "n/a"), 0)
    for r in records:
        p, ref = _confusion_key(r.get(pred_key), r.get(ref_key))
        matrix[p][ref] = matrix[p].get(ref, 0) + 1
    return matrix


def _hit_rate_vs_market(
    records: list[dict], pred_key: str, horizon: str, threshold: float
) -> dict | None:
    """Hit rate d'un predictor vs marché réel à un horizon donné."""
    eligible = [
        r
        for r in records
        if r.get(pred_key) is not None and r.get("deltas", {}).get(horizon, {}).get("available")
    ]
    if not eligible:
        return None
    n_correct = sum(
        1
        for r in eligible
        if _verdict_correct_vs_market(r[pred_key], r["deltas"][horizon]["delta_pct"], threshold)
    )
    return {
        "n": len(eligible),
        "n_correct": n_correct,
        "hit_rate": n_correct / len(eligible),
    }


def _baseline_random_hit_rate(
    records: list[dict], horizon: str, threshold: float, n_runs: int = 100, seed: int = 42
) -> dict | None:
    """Baseline random uniforme moyenné sur n_runs."""
    eligible = [r for r in records if r.get("deltas", {}).get(horizon, {}).get("available")]
    if not eligible:
        return None
    rng = random.Random(seed)
    total_correct = 0
    for _ in range(n_runs):
        for r in eligible:
            v = rng.choice(VERDICTS)
            if _verdict_correct_vs_market(v, r["deltas"][horizon]["delta_pct"], threshold):
                total_correct += 1
    total_evals = len(eligible) * n_runs
    return {
        "n": len(eligible),
        "n_correct": total_correct / n_runs,
        "hit_rate": total_correct / total_evals,
    }


def _baseline_constant_hit_rate(
    records: list[dict], verdict: str, horizon: str, threshold: float
) -> dict | None:
    """Baseline 'always X' (always bull/bear/neutral)."""
    eligible = [r for r in records if r.get("deltas", {}).get(horizon, {}).get("available")]
    if not eligible:
        return None
    n_correct = sum(
        1
        for r in eligible
        if _verdict_correct_vs_market(verdict, r["deltas"][horizon]["delta_pct"], threshold)
    )
    return {
        "n": len(eligible),
        "n_correct": n_correct,
        "hit_rate": n_correct / len(eligible),
    }


# === Construction du dataset combiné ===


def _build_combined(
    items: list[dict],
    annotations: dict[str, dict],
    predictions: dict[str, dict],
    prices: dict[str, dict],
) -> list[dict]:
    """Joint les 4 sources par id."""
    out: list[dict] = []
    for item in items:
        item_id = item["id"]
        ann = annotations.get(item_id) or {}
        pred = predictions.get(item_id) or {}
        price = prices.get(item_id) or {}

        pred_kw = (pred.get("predictions") or {}).get("keywords") or {}
        pred_ol = (pred.get("predictions") or {}).get("ollama") or {}

        out.append(
            {
                "id": item_id,
                "asset": item["asset"],
                "source": item["source"],
                "text": item["text"],
                "human": ann.get("verdict"),
                "ollama": pred_ol.get("verdict"),
                "keywords": pred_kw.get("verdict"),
                "deltas": price.get("deltas") or {},
            }
        )
    return out


# === Sections du rapport ===


def _section_distribution(records: list[dict]) -> dict:
    """Distribution des verdicts par classifier."""
    out: dict[str, dict] = {}
    for col in ("human", "ollama", "keywords"):
        counts: dict[str, int] = dict.fromkeys((*VERDICTS, "n/a"), 0)
        for r in records:
            v = r.get(col)
            counts[v if v in VERDICTS else "n/a"] += 1
        total = sum(counts.values())
        out[col] = {
            "counts": counts,
            "pct": {k: (v / total * 100 if total else 0.0) for k, v in counts.items()},
            "total": total,
        }
    return out


def _section_concordance(records: list[dict]) -> dict:
    """Concordance humain ↔ classifier (Ollama et keywords)."""
    return {
        "human_vs_ollama": {
            "accuracy": _accuracy(records, "ollama", "human"),
            "confusion": _confusion_matrix(records, "ollama", "human"),
        },
        "human_vs_keywords": {
            "accuracy": _accuracy(records, "keywords", "human"),
            "confusion": _confusion_matrix(records, "keywords", "human"),
        },
        "ollama_vs_keywords": {
            "accuracy": _accuracy(records, "ollama", "keywords"),
            "confusion": _confusion_matrix(records, "ollama", "keywords"),
        },
    }


def _section_market_calibration(records: list[dict], horizons: list[str], threshold: float) -> dict:
    """Hit rate vs marché pour chaque predictor à chaque horizon."""
    out: dict[str, dict] = {}
    for h in horizons:
        out[h] = {
            "human": _hit_rate_vs_market(records, "human", h, threshold),
            "ollama": _hit_rate_vs_market(records, "ollama", h, threshold),
            "keywords": _hit_rate_vs_market(records, "keywords", h, threshold),
            "baselines": {
                "random": _baseline_random_hit_rate(records, h, threshold),
                "always_bull": _baseline_constant_hit_rate(records, "bull", h, threshold),
                "always_bear": _baseline_constant_hit_rate(records, "bear", h, threshold),
                "always_neutral": _baseline_constant_hit_rate(records, "neutral", h, threshold),
            },
        }
    return out


def _section_per_source(records: list[dict], horizons: list[str], threshold: float) -> dict:
    """Hit rate par source × predictor à chaque horizon."""
    by_source: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_source[r["source"]].append(r)

    out: dict[str, dict] = {}
    for source, rs in by_source.items():
        out[source] = {
            "n_total": len(rs),
            "by_asset": dict(_count_by_asset(rs)),
            "horizons": {
                h: {
                    "human": _hit_rate_vs_market(rs, "human", h, threshold),
                    "ollama": _hit_rate_vs_market(rs, "ollama", h, threshold),
                    "keywords": _hit_rate_vs_market(rs, "keywords", h, threshold),
                }
                for h in horizons
            },
        }
    return out


def _count_by_asset(records: list[dict]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for r in records:
        out[r["asset"]] += 1
    return out


# === Rendu Markdown ===


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:5.1f}%"


def _fmt_count(stats: dict | None) -> str:
    if stats is None:
        return "  n/a"
    return (
        f"{stats['n_correct']:>4.1f}/{stats['n']:<3d}"
        if isinstance(stats["n_correct"], float)
        else f"{stats['n_correct']:>4d}/{stats['n']:<3d}"
    )


def _render_markdown(report: dict) -> str:
    lines: list[str] = []
    meta = report["meta"]
    lines.append("# Rapport de calibration — golden dataset Tik")
    lines.append("")
    lines.append(f"*Généré le {meta['generated_at']}*")
    lines.append("")
    lines.append(
        f"- **Items totaux** : {meta['n_total']} ({meta['n_btc']} BTC + {meta['n_gold']} GOLD)"
    )
    lines.append(f"- **Items annotés à la main** : {meta['n_annotated']}")
    lines.append(f"- **Items avec prediction Ollama** : {meta['n_ollama']}")
    lines.append(f"- **Horizons évalués** : {', '.join(meta['horizons'])}")
    lines.append(f"- **Seuil de succès delta** : ±{meta['threshold']}%")
    lines.append("")

    # Distribution
    lines.append("## 1. Distribution des verdicts")
    lines.append("")
    lines.append("| Verdict | Humain | Ollama | Keywords |")
    lines.append("|---|---:|---:|---:|")
    dist = report["distribution"]
    for v in (*VERDICTS, "n/a"):
        h = dist["human"]["counts"].get(v, 0)
        o = dist["ollama"]["counts"].get(v, 0)
        k = dist["keywords"]["counts"].get(v, 0)
        h_pct = dist["human"]["pct"].get(v, 0.0)
        o_pct = dist["ollama"]["pct"].get(v, 0.0)
        k_pct = dist["keywords"]["pct"].get(v, 0.0)
        lines.append(f"| **{v}** | {h} ({h_pct:.0f}%) | {o} ({o_pct:.0f}%) | {k} ({k_pct:.0f}%) |")
    lines.append("")

    # Concordance
    lines.append("## 2. Concordance humain ↔ classifier")
    lines.append("")
    conc = report["concordance"]
    lines.append(
        f"- **Accuracy Humain ↔ Ollama** : {_fmt_pct(conc['human_vs_ollama']['accuracy'])}"
    )
    lines.append(
        f"- **Accuracy Humain ↔ Keywords** : {_fmt_pct(conc['human_vs_keywords']['accuracy'])}"
    )
    lines.append(
        f"- **Accuracy Ollama ↔ Keywords** : {_fmt_pct(conc['ollama_vs_keywords']['accuracy'])}"
    )
    lines.append("")
    lines.append("### Confusion matrix Humain (référence) ↔ Ollama (prediction)")
    lines.append("")
    lines.append("Lecture : ligne = ce qu'Ollama a prédit, colonne = ce que l'humain a annoté.")
    lines.append("Diagonale = accord. Hors-diagonale = divergence.")
    lines.append("")
    cm = conc["human_vs_ollama"]["confusion"]
    refs = (*VERDICTS, "n/a")
    lines.append("| Ollama \\ Humain | " + " | ".join(refs) + " |")
    lines.append("|---" * (len(refs) + 1) + "|")
    for v_pred in refs:
        row = [str(cm[v_pred].get(v_ref, 0)) for v_ref in refs]
        lines.append(f"| **{v_pred}** | " + " | ".join(row) + " |")
    lines.append("")

    # Market calibration
    lines.append("## 3. Calibration vs marché réel")
    lines.append("")
    lines.append(
        "*La vérité de référence objective. Compare chaque predictor au mouvement réel du prix.*"
    )
    lines.append("")
    market = report["market_calibration"]
    for h in meta["horizons"]:
        h_data = market.get(h)
        if not h_data:
            continue
        lines.append(f"### Horizon {h}")
        lines.append("")
        lines.append("| Predictor | n correct / n | hit rate |")
        lines.append("|---|---|---:|")
        for predictor in ("human", "ollama", "keywords"):
            stats = h_data.get(predictor)
            if stats is None:
                lines.append(f"| {predictor} | n/a | n/a |")
            else:
                n_correct = stats["n_correct"]
                n_correct_str = (
                    f"{n_correct:.1f}" if isinstance(n_correct, float) else str(n_correct)
                )
                lines.append(
                    f"| **{predictor}** | "
                    f"{n_correct_str} / {stats['n']} | "
                    f"{_fmt_pct(stats['hit_rate'])} |"
                )
        lines.append("")
        lines.append("**Baselines** (pour comparaison) :")
        lines.append("")
        lines.append("| Baseline | n correct / n | hit rate |")
        lines.append("|---|---|---:|")
        for bl in ("random", "always_bull", "always_bear", "always_neutral"):
            stats = h_data["baselines"].get(bl)
            if stats is None:
                continue
            n_correct_str = (
                f"{stats['n_correct']:.1f}"
                if isinstance(stats["n_correct"], float)
                else str(stats["n_correct"])
            )
            lines.append(
                f"| {bl} | {n_correct_str} / {stats['n']} | {_fmt_pct(stats['hit_rate'])} |"
            )
        lines.append("")

    # Per-source
    lines.append("## 4. Performance par source")
    lines.append("")
    lines.append("*Pour chaque source d'items, hit rate par predictor sur l'horizon principal.*")
    lines.append("")
    main_horizon = meta["horizons"][-1] if meta["horizons"] else None
    if main_horizon:
        lines.append(f"### Horizon de référence : {main_horizon}")
        lines.append("")
        lines.append("| Source | n total | hit human | hit ollama | hit keywords |")
        lines.append("|---|---:|---:|---:|---:|")
        per_src = report["per_source"]
        for source, src_data in sorted(per_src.items()):
            h_data = src_data["horizons"].get(main_horizon, {})
            lines.append(
                f"| **{source}** | {src_data['n_total']} | "
                f"{_fmt_pct((h_data.get('human') or {}).get('hit_rate'))} | "
                f"{_fmt_pct((h_data.get('ollama') or {}).get('hit_rate'))} | "
                f"{_fmt_pct((h_data.get('keywords') or {}).get('hit_rate'))} |"
            )
        lines.append("")

    # Conclusions / suggestions
    lines.append("## 5. Pistes d'ajustement")
    lines.append("")
    lines.append(
        "Cette section est un **brouillon machine-générée**. À relire à la main "
        "avant tout ajustement structurel de Tik."
    )
    lines.append("")
    lines.append(
        "1. Si l'accuracy **Humain ↔ Ollama** est faible (<60%), c'est un signal "
        "fort que le LLM ne capte pas la sémantique financière comme un humain. "
        "À ce stade, ne pas survaloriser Ollama dans `SOURCE_SCORES`."
    )
    lines.append(
        "2. Si une source a un hit rate vs marché **significativement supérieur** "
        "à la moyenne (delta > 10 points), augmenter son entrée dans `SOURCE_SCORES`."
    )
    lines.append(
        "3. Si Tik (humain ou Ollama) **bat le baseline 'always X' le plus performant** "
        "sur la fenêtre testée, c'est qu'on apporte un edge réel. Sinon, on est dans le bruit."
    )
    lines.append(
        "4. Limites assumées : échantillon de ~100 items, période courte, pas de coûts "
        "de transaction. À élargir en Session 5+ avec plus d'items et plusieurs cycles "
        "de marché."
    )
    lines.append("")

    return "\n".join(lines)


# === Main ===


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mesure de calibration sur le golden dataset.",
    )
    parser.add_argument("--items", type=Path, default=RAW_ITEMS_FILE)
    parser.add_argument("--annotations", type=Path, default=ANNOTATIONS_FILE)
    parser.add_argument("--predictions", type=Path, default=PREDICTIONS_FILE)
    parser.add_argument("--prices", type=Path, default=PRICES_FILE)
    parser.add_argument("--out-json", type=Path, default=REPORT_JSON_FILE)
    parser.add_argument("--out-md", type=Path, default=REPORT_MD_FILE)
    parser.add_argument(
        "--horizons",
        type=str,
        default="1h,6h,24h,5d",
        help="Liste des horizons à évaluer (doit être inclus dans prices.jsonl).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Seuil delta %% pour qu'un signal soit jugé 'correct' (défaut 0.5%%).",
    )
    args = parser.parse_args()

    items = _load_jsonl(args.items)
    if not items:
        print(f"raw_items.jsonl manquant ou vide ({args.items}).", file=sys.stderr)
        sys.exit(1)
    annotations = _index_by_id(_load_jsonl(args.annotations))
    predictions = _index_by_id(_load_jsonl(args.predictions))
    prices = _index_by_id(_load_jsonl(args.prices))

    horizons = [h.strip() for h in args.horizons.split(",") if h.strip()]
    records = _build_combined(items, annotations, predictions, prices)

    n_btc = sum(1 for r in records if r["asset"] == "btc")
    n_gold = sum(1 for r in records if r["asset"] == "gold")
    n_annotated = sum(1 for r in records if r["human"] is not None)
    n_ollama = sum(1 for r in records if r["ollama"] is not None)

    report = {
        "meta": {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "n_total": len(records),
            "n_btc": n_btc,
            "n_gold": n_gold,
            "n_annotated": n_annotated,
            "n_ollama": n_ollama,
            "horizons": horizons,
            "threshold": args.threshold,
        },
        "distribution": _section_distribution(records),
        "concordance": _section_concordance(records),
        "market_calibration": _section_market_calibration(records, horizons, args.threshold),
        "per_source": _section_per_source(records, horizons, args.threshold),
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.out_md.write_text(_render_markdown(report), encoding="utf-8")

    print(f"Rapport JSON : {args.out_json}")
    print(f"Rapport Markdown : {args.out_md}")
    print()
    print("--- Résumé ---")
    print(f"Items annotés : {n_annotated}/{len(records)}")
    print(f"Items prédits Ollama : {n_ollama}/{len(records)}")

    conc = report["concordance"]
    print(f"\nAccuracy Humain ↔ Ollama : {_fmt_pct(conc['human_vs_ollama']['accuracy'])}")
    print(f"Accuracy Humain ↔ Keywords : {_fmt_pct(conc['human_vs_keywords']['accuracy'])}")

    # Affiche tous les horizons dans le résumé console, en marquant explicitement
    # ceux qui n'ont pas encore de data dispo (horizon dans le futur).
    print("\nHit rate vs marché par horizon :")
    for h in horizons:
        h_data = report["market_calibration"].get(h)
        if not h_data:
            continue
        any_data = any(h_data.get(p) is not None for p in ("human", "ollama", "keywords"))
        if not any_data:
            print(f"  [{h:>4s}] pas encore de data (horizon dans le futur)")
            continue
        print(f"  [{h:>4s}]")
        for predictor in ("human", "ollama", "keywords"):
            stats = h_data.get(predictor)
            if stats is None:
                print(f"    {predictor:10s} : n/a")
                continue
            n_correct = stats["n_correct"]
            n_correct_str = f"{n_correct:.1f}" if isinstance(n_correct, float) else str(n_correct)
            print(
                f"    {predictor:10s} : {_fmt_pct(stats['hit_rate'])} "
                f"({n_correct_str}/{stats['n']})"
            )


if __name__ == "__main__":
    main()
