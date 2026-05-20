"""Génération des predictions classifier sur le golden dataset.

Pour chaque item de raw_items.jsonl, on appelle deux classifiers :
- `KeywordClassifier` (analyse mots-clés, asset-agnostic)
- `OllamaClassifier` (LLM local llama3.2:3b, **asset-aware** : un classifier
  par asset BTC/GOLD avec son `asset_name` injecté dans le prompt — cf. ADR-008)

Les predictions sont stockées dans predictions.jsonl, lié aux annotations
manuelles par le hash `id` stable. Le script suivant (measure_calibration.py)
compare predictions ↔ annotations + delta prix réel pour calculer hit rate
par source, confusion matrix, et calibration de la veracity.

Blindness : ce script doit être lancé APRÈS la fin de l'annotation manuelle
(annotate_golden.py). Sinon les annotations futures pourraient être polluées
si l'annotateur consulte les predictions par mégarde.

Usage:
    docker compose exec core python -m tik_core.scripts.predict_golden
    docker compose exec core python -m tik_core.scripts.predict_golden --reset

Format de sortie (core/data/golden_dataset/predictions.jsonl) :
    {
      "id": "<hash16>",
      "asset": "btc" | "gold",
      "source": "google_news" | "cryptocompare" | "reddit",
      "predictions": {
        "keywords": {
          "verdict": "bull" | "bear" | "neutral",
          "n_bull": int, "n_bear": int,
          "method": "keywords"
        },
        "ollama": {
          "verdict": "bull" | "bear" | "neutral" | null,
          "method": "ollama:llama3.2:3b" | null
        }
      },
      "predicted_at": "..."
    }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog

from tik_core.aggregator.news_classifier import (
    KeywordClassifier,
    NewsClassifier,
    OllamaClassifier,
    build_news_classifier,
)
from tik_core.config import get_settings

log = structlog.get_logger()

DATA_DIR = Path("/app/data/golden_dataset")
RAW_ITEMS_FILE = DATA_DIR / "raw_items.jsonl"
PREDICTIONS_FILE = DATA_DIR / "predictions.jsonl"

# Mapping asset → asset_name (passé au prompt Ollama). Aligné avec les
# ingesters de prod : `Bitcoin` pour CC/GoogleNews/Reddit, `Gold` pour
# GoogleNews GOLD (cf. run_ingesters.py).
ASSET_NAMES: dict[str, str] = {
    "btc": "Bitcoin",
    "gold": "Gold",
}


def _load_raw_items(path: Path) -> list[dict]:
    if not path.exists():
        print(
            f"Le fichier {path} n'existe pas. "
            f"Lance d'abord : python -m tik_core.scripts.collect_golden",
            file=sys.stderr,
        )
        sys.exit(1)
    items: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def _load_existing_predictions(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in obj:
                ids.add(obj["id"])
    return ids


def _verdict_from_counts(n_bull: int, n_bear: int) -> str:
    """Convertit (n_bull, n_bear) en trinaire bull/bear/neutral."""
    if n_bull > n_bear:
        return "bull"
    if n_bear > n_bull:
        return "bear"
    return "neutral"


async def _build_ollama_classifiers(
    settings, assets_needed: set[str]
) -> dict[str, OllamaClassifier]:
    """Construit un OllamaClassifier par asset présent dans le dataset.

    Construction parallèle via asyncio.gather pour ne pas pinger Ollama
    plusieurs fois en série au boot. Si Ollama est indisponible, la
    factory retourne un KeywordClassifier en fallback : on l'écarte ici
    et le script continue sans prediction Ollama (les keywords suffisent
    pour produire le rapport, juste avec une colonne en moins).
    """
    if settings.news_classifier != "ollama":
        log.info("predict_golden.ollama_disabled_in_settings")
        return {}

    assets_list = sorted(assets_needed)
    coros = [
        build_news_classifier(
            "ollama",
            settings.ollama_url,
            settings.ollama_model,
            asset_name=ASSET_NAMES.get(asset, asset.upper()),
        )
        for asset in assets_list
    ]
    classifiers = await asyncio.gather(*coros)

    out: dict[str, OllamaClassifier] = {}
    for asset, clf in zip(assets_list, classifiers, strict=True):
        if isinstance(clf, OllamaClassifier):
            out[asset] = clf
        else:
            log.warning(
                "predict_golden.ollama_unavailable_for_asset",
                asset=asset,
            )
    return out


async def _predict_item(
    item: dict,
    keyword_clf: NewsClassifier,
    ollama_clfs: dict[str, OllamaClassifier],
) -> dict:
    text = item["text"]
    asset = item["asset"]

    # Keywords : asset-agnostic, sync interne mais on respecte l'API async
    n_bull_kw, n_bear_kw = await keyword_clf.classify(text)
    keyword_verdict = _verdict_from_counts(n_bull_kw, n_bear_kw)

    # Ollama : asset-aware, classifier dédié si dispo
    ollama_verdict: str | None = None
    ollama_method: str | None = None
    ollama_clf = ollama_clfs.get(asset)
    if ollama_clf is not None:
        n_bull_ol, n_bear_ol = await ollama_clf.classify(text)
        ollama_verdict = _verdict_from_counts(n_bull_ol, n_bear_ol)
        ollama_method = ollama_clf.method_name

    return {
        "id": item["id"],
        "asset": asset,
        "source": item["source"],
        "predictions": {
            "keywords": {
                "verdict": keyword_verdict,
                "n_bull": n_bull_kw,
                "n_bear": n_bear_kw,
                "method": keyword_clf.method_name,
            },
            "ollama": {
                "verdict": ollama_verdict,
                "method": ollama_method,
            },
        },
        "predicted_at": datetime.now(tz=UTC).isoformat(),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Génère les predictions classifier sur le golden dataset."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=RAW_ITEMS_FILE,
        help=f"raw_items.jsonl (défaut: {RAW_ITEMS_FILE}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PREDICTIONS_FILE,
        help=f"predictions.jsonl (défaut: {PREDICTIONS_FILE}).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Efface predictions.jsonl avant de commencer.",
    )
    args = parser.parse_args()

    settings = get_settings()

    if args.reset and args.output.exists():
        args.output.unlink()
        print(f"--reset : {args.output} supprimé.")

    items = _load_raw_items(args.input)
    existing = _load_existing_predictions(args.output)
    todo = [i for i in items if i["id"] not in existing]

    print(f"Items à prédire : {len(todo)}/{len(items)} (déjà prédit : {len(existing)})")
    if not todo:
        print("Tout est déjà prédit. Rien à faire.")
        return

    assets_needed = {i["asset"] for i in todo}
    print(f"Assets dans le batch : {sorted(assets_needed)}")

    keyword_clf = KeywordClassifier()
    ollama_clfs = await _build_ollama_classifiers(settings, assets_needed)

    if ollama_clfs:
        print(f"Ollama prêt sur {len(ollama_clfs)} asset(s) : {sorted(ollama_clfs.keys())}")
    else:
        print("⚠ Ollama indisponible — predictions keyword-only.")

    # Réarme les circuit breakers Ollama batch-level avant de démarrer le run
    for clf in ollama_clfs.values():
        clf.reset_batch()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    n_done = 0
    try:
        with open(args.output, "a", encoding="utf-8") as f:
            for i, item in enumerate(todo, start=1):
                result = await _predict_item(item, keyword_clf, ollama_clfs)
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                f.flush()  # ne pas perdre la progression sur Ctrl+C
                n_done += 1
                if i % 10 == 0 or i == len(todo):
                    print(f"  {i}/{len(todo)} prédits")
    finally:
        for clf in ollama_clfs.values():
            await clf.aclose()

    print(f"\n{n_done} predictions écrites dans {args.output}")

    # Stats rapides : distribution des verdicts par classifier
    counts_kw = {"bull": 0, "bear": 0, "neutral": 0}
    counts_ol = {"bull": 0, "bear": 0, "neutral": 0, "n/a": 0}
    with open(args.output, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            kw = obj["predictions"]["keywords"]["verdict"]
            ol = obj["predictions"]["ollama"]["verdict"]
            counts_kw[kw] = counts_kw.get(kw, 0) + 1
            if ol is None:
                counts_ol["n/a"] += 1
            else:
                counts_ol[ol] = counts_ol.get(ol, 0) + 1

    print("\n--- Distribution des verdicts (toutes les predictions) ---")
    print(f"  {'verdict':10s} | {'keywords':>10s} | {'ollama':>10s}")
    print("  " + "-" * 36)
    for v in ("bull", "bear", "neutral"):
        print(f"  {v:10s} | {counts_kw.get(v, 0):>10d} | {counts_ol.get(v, 0):>10d}")
    if counts_ol.get("n/a", 0):
        print(f"  {'n/a':10s} | {'-':>10s} | {counts_ol['n/a']:>10d}")


if __name__ == "__main__":
    asyncio.run(main())
