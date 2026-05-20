"""Annotation manuelle blinded du golden dataset.

CLI interactif qui parcourt raw_items.jsonl dans un ordre randomisé (seed
fixe pour reproductibilité), affiche chaque item sans aucune prediction,
et demande un verdict trinaire (bull/bear/neutral).

Blindness : ce script ne charge PAS predictions.jsonl. Tu dois annoter
AVANT de générer les predictions du classifier (predict_golden.py), sinon
ton jugement sera contaminé. Une fois les predictions générées, n'utilise
plus ce script pour annoter de nouveaux items du même dataset.

Resume-friendly : append immédiat à annotations.jsonl ligne par ligne. Si
tu fais Ctrl+C ou tu utilises 'q', les annotations déjà faites sont
sauvegardées. Relance le script pour continuer où tu t'es arrêté.

Usage:
    docker compose exec -it core python -m tik_core.scripts.annotate_golden

    # Pour repartir de zéro (efface les annotations existantes) :
    docker compose exec -it core python -m tik_core.scripts.annotate_golden --reset

Format de sortie (core/data/golden_dataset/annotations.jsonl) :
    {
      "id": "<hash16>",
      "verdict": "bull" | "bear" | "neutral",
      "annotated_at": "2026-05-01T18:30:00+00:00"
    }
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from tik_core.config import get_settings

DATA_DIR = Path("/app/data/golden_dataset")
RAW_ITEMS_FILE = DATA_DIR / "raw_items.jsonl"
ANNOTATIONS_FILE = DATA_DIR / "annotations.jsonl"
DEFAULT_SEED = 42

TRANSLATE_PROMPT = (
    "You are a precise translator for financial news headlines. "
    "Translate the English headline to French.\n\n"
    "STRICT RULES:\n"
    "1. Keep these technical terms in ENGLISH (do NOT translate, do NOT paraphrase): "
    "whales, supply, demand, holders, hodlers, mining, miners, hashrate, halving, "
    "ETF, ATH, FUD, FOMO, hawkish, dovish, easing, tightening, QE, QT, DXY, FOMC, "
    "Fed, real yields, yields, basis points, bps, bull, bear, bullish, bearish, "
    "pump, dump, rally, surge, plunge, crash, tumble, breakout, breakdown, "
    "support, resistance, oversold, overbought, long, short, leverage, "
    "liquidation, custody, staking, on-chain, mempool, MVRV, inflows, outflows, "
    "safe haven, soft landing, recession, stagflation, CPI, PPI.\n"
    "2. Translate literally. Do NOT interpret or extrapolate.\n"
    "3. Keep all numbers, currencies ($, €), tickers and proper names (companies, "
    "people, products) exactly as written.\n"
    "4. If unsure about a word, keep it in English.\n"
    "5. Reply with ONLY the French translation. No explanation, no quotes, "
    "no preamble.\n\n"
    "Headline: {title}"
)

VERDICT_MAP = {
    "b": "bull",
    "bull": "bull",
    "s": "bear",
    "bear": "bear",
    "n": "neutral",
    "neutral": "neutral",
}


@dataclass
class RawItem:
    id: str
    asset: str
    source: str
    text: str
    metadata: dict
    fetched_at: str
    fetch_price: float | None


def _load_raw_items(path: Path) -> list[RawItem]:
    if not path.exists():
        print(
            f"Le fichier {path} n'existe pas. Lance d'abord :\n"
            f"  python -m tik_core.scripts.collect_golden",
            file=sys.stderr,
        )
        sys.exit(1)
    items: list[RawItem] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            items.append(
                RawItem(
                    id=obj["id"],
                    asset=obj["asset"],
                    source=obj["source"],
                    text=obj["text"],
                    metadata=obj.get("metadata", {}),
                    fetched_at=obj["fetched_at"],
                    fetch_price=obj.get("fetch_price"),
                )
            )
    return items


def _load_existing_annotations(path: Path) -> set[str]:
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


def _translate_to_french(title: str, ollama_url: str, ollama_model: str) -> str | None:
    """Traduit un titre anglais en français via Ollama (sync, ~1-2s par titre).

    Retourne None si Ollama indisponible / timeout / réponse vide. Le script
    continuera sans traduction (affichage EN seul) sans crasher.
    """
    if not ollama_url:
        return None
    prompt = TRANSLATE_PROMPT.format(title=title.replace('"', "'"))
    try:
        r = httpx.post(
            f"{ollama_url.rstrip('/')}/api/generate",
            json={
                "model": ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": 120},
            },
            timeout=15.0,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None
    text = (data.get("response") or "").strip()
    return text or None


def _format_metadata(item: RawItem) -> str:
    """Affichage du contexte selon la source.

    On affiche les infos qui aident l'annotation (publisher, score, sub),
    PAS les predictions ou les scores agrégés.
    """
    md = item.metadata or {}
    if item.source == "google_news":
        publisher = md.get("publisher", "unknown")
        published = md.get("published", "")
        return f"Publisher: {publisher} · {published}"
    if item.source == "cryptocompare":
        source_name = md.get("source_name", "unknown")
        cats = md.get("categories", "")
        return f"Source: {source_name} · Categories: {cats}"
    if item.source == "reddit":
        sub = md.get("subreddit", "unknown")
        score = md.get("score", 0)
        n_comments = md.get("num_comments", 0)
        return f"r/{sub} · score: {score} · {n_comments} comments"
    return ""


def _print_item(
    item: RawItem,
    idx: int,
    total: int,
    translation: str | None = None,
) -> None:
    print()
    print("=" * 70)
    print(f"  [{idx}/{total}]  {item.asset.upper()} / {item.source}")
    meta_line = _format_metadata(item)
    if meta_line:
        print(f"  {meta_line}")
    print("=" * 70)
    print()
    print(f"  EN  {item.text}")
    if translation:
        print(f"  FR  {translation}")
    print()


def _prompt_verdict() -> str | None:
    """Lit un verdict valide ou None si quit/skip.

    Retours possibles :
    - "bull" / "bear" / "neutral" : annotation
    - "skip" : item reporté
    - "quit" : sortir cleanly
    - None : input invalide, on re-prompt
    """
    raw = input("  bull (b) / bear (s) / neutral (n) / skip (?) / quit (q) : ").strip().lower()
    if raw in ("q", "quit"):
        return "quit"
    if raw in ("?", "skip"):
        return "skip"
    if raw in VERDICT_MAP:
        return VERDICT_MAP[raw]
    return None


def _append_annotation(path: Path, item_id: str, verdict: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "id": item_id,
                    "verdict": verdict,
                    "annotated_at": datetime.now(tz=UTC).isoformat(),
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def _shuffle_items(items: list[RawItem], seed: int) -> list[RawItem]:
    rng = random.Random(seed)
    shuffled = list(items)
    rng.shuffle(shuffled)
    return shuffled


def _print_summary(annotations_path: Path) -> None:
    if not annotations_path.exists():
        print("Aucune annotation enregistrée.")
        return
    counts = {"bull": 0, "bear": 0, "neutral": 0}
    total = 0
    with open(annotations_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            v = obj.get("verdict")
            if v in counts:
                counts[v] += 1
                total += 1
    print()
    print("=" * 70)
    print("  RÉCAP ANNOTATIONS")
    print("=" * 70)
    print(f"  Total annotés : {total}")
    for verdict, n in sorted(counts.items()):
        pct = n / total * 100 if total else 0.0
        print(f"  {verdict:8s} : {n:3d} ({pct:5.1f}%)")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Annotation manuelle blinded du golden dataset.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=RAW_ITEMS_FILE,
        help=f"Fichier d'items à annoter (défaut: {RAW_ITEMS_FILE}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ANNOTATIONS_FILE,
        help=f"Fichier de sortie des annotations (défaut: {ANNOTATIONS_FILE}).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Seed du shuffle pour reproductibilité (défaut {DEFAULT_SEED}).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Efface annotations.jsonl avant de commencer.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Affiche juste le récap des annotations existantes et sort.",
    )
    parser.add_argument(
        "--no-translate",
        action="store_true",
        help="Désactive la traduction française live via Ollama (annotation EN-only).",
    )
    args = parser.parse_args()

    if args.summary:
        _print_summary(args.output)
        return

    if args.reset and args.output.exists():
        args.output.unlink()
        print(f"--reset : {args.output} supprimé.")

    items = _load_raw_items(args.input)
    items = _shuffle_items(items, args.seed)
    existing = _load_existing_annotations(args.output)

    todo = [item for item in items if item.id not in existing]
    total = len(items)
    done = total - len(todo)

    if not todo:
        print(f"Tous les items ({total}) sont déjà annotés. Rien à faire.")
        _print_summary(args.output)
        return

    settings = get_settings()
    translate = not args.no_translate
    if translate:
        print(
            f"\nTraduction live activée via Ollama "
            f"(modèle {settings.ollama_model}). "
            f"Désactiver avec --no-translate.\n"
        )

    print(
        f"Annotation : {done}/{total} déjà fait, "
        f"{len(todo)} restant(s). Seed = {args.seed}.\n"
        f"Tape 'q' pour sauvegarder et sortir, '?' pour skip un item.\n"
    )

    try:
        for offset, item in enumerate(todo, start=1):
            idx = done + offset
            translation: str | None = None
            if translate:
                translation = _translate_to_french(
                    item.text,
                    settings.ollama_url,
                    settings.ollama_model,
                )
            _print_item(item, idx, total, translation=translation)
            while True:
                verdict = _prompt_verdict()
                if verdict is None:
                    print("  Input non reconnu. Réessaie.")
                    continue
                break
            if verdict == "quit":
                print("\nSortie demandée. Annotations sauvegardées.")
                break
            if verdict == "skip":
                print("  → reporté.")
                continue
            _append_annotation(args.output, item.id, verdict)
            print(f"  → {verdict} enregistré.")
    except KeyboardInterrupt:
        print("\n\nInterruption clavier. Annotations sauvegardées.")
    except EOFError:
        print("\n\nEOF (entrée fermée). Annotations sauvegardées.")

    _print_summary(args.output)


if __name__ == "__main__":
    main()
