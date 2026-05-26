"""Archiveur SHADOW du calendrier macro ForexFactory (faireconomy mirror).

Pourquoi ce script existe
-------------------------
Le feed gratuit `nfs.faireconomy.media/ff_calendar_thisweek.json` porte, pour
chaque événement macro : `forecast` (le **consensus** = vraie attente du
marché), `previous`, `actual` (rempli APRÈS la release), `impact`, `title`,
`country`, `date`. C'est la seule source gratuite vérifiée (2026-05-27) qui
donne un vrai *consensus* → permet de calculer une **surprise = actual −
forecast** (ce que FRED ne donne pas : FRED ne fournit que actuel − précédent,
un proxy de momentum, et en retard).

MAIS le feed est **rolling-week** (semaine glissante) : impossible de récupérer
l'historique a posteriori. Pour pouvoir backtester la valeur prédictive de la
surprise plus tard (IC Spearman surprise ↔ delta prix futur, hit rate, gain),
il faut **accumuler les snapshots dans le temps DÈS MAINTENANT**. Ce script
fait exactement ça, et rien d'autre.

Mode SHADOW STRICT — garde-fous
-------------------------------
- N'est PAS enregistré dans `run_ingesters.py`. Aucun ingester Tik ne tourne
  ce code automatiquement (à cron-er manuellement, cf. ci-dessous).
- N'écrit RIEN dans Redis ni dans la base `signals`. Écrit uniquement un
  fichier JSONL sous `core/data/forexfactory_archive/` (volume `./data`).
- Aucun `_enrich_with_forexfactory` n'existe → cette donnée **n'entre pas**
  dans le `combined_bias` / la direction / la veracity des signaux Tik.
- Best-effort : toute erreur réseau/parse → log warning + exit 0 (jamais de
  crash, jamais de demi-écriture).

Conforme `docs/backlog-osint.md` (V1.6 candidat) règle SHADOW vs ENRÔLEMENT :
collecter ≠ enrôler. L'enrôlement directionnel reste gaté (NO-GO go/no-go
27/05 + mesure ≥ 2 semaines à venir).

Usage (depuis le VPS, dans le conteneur core)
---------------------------------------------
    docker exec tik-core python -m tik_core.scripts.archive_forexfactory
    docker exec tik-core python -m tik_core.scripts.archive_forexfactory --dedup
    docker exec tik-core python -m tik_core.scripts.archive_forexfactory --stats

Cron suggéré (capture forecast à l'annonce PUIS actual après release) — à
ajouter côté VPS, PAS automatique :
    0 */2 * * *  docker exec tik-core python -m tik_core.scripts.archive_forexfactory --dedup >/dev/null 2>&1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

# Feed gratuit ForexFactory (mirror faireconomy, utilisé par les EAs MT4/MT5).
# Vérifié 2026-05-27 : SEUL `thisweek` répond 200 ; nextweek/lastweek/thismonth
# renvoient 404 chez faireconomy. On reste donc sur thisweek (semaine glissante),
# d'où la nécessité de snapshots fréquents pour capter les `actual` qui se
# remplissent en cours de semaine.
FEED_URLS: dict[str, str] = {
    "thisweek": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
}

USER_AGENT = "tik-osint-bot/0.1 (research; contact escltheo@gmail.com)"

# Volume Docker `./data:/app/data:rw` (cf. core/docker-compose.yml). Overridable
# pour un run hors conteneur via TIK_DATA_DIR.
DATA_DIR = Path(os.environ.get("TIK_DATA_DIR", "/app/data")) / "forexfactory_archive"
SNAPSHOTS_FILE = DATA_DIR / "snapshots.jsonl"


def fetch_feed(feed: str, client: httpx.Client) -> list[dict[str, Any]] | None:
    """Récupère un feed ForexFactory. Retourne None en cas d'échec (best-effort)."""
    url = FEED_URLS[feed]
    try:
        r = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=25.0)
        if r.status_code != 200:
            log.warning("forexfactory.fetch.bad_status", feed=feed, status=r.status_code)
            return None
        data = r.json()
        if not isinstance(data, list):
            log.warning("forexfactory.fetch.unexpected_payload", feed=feed, type=str(type(data)))
            return None
        return data
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        log.warning("forexfactory.fetch.error", feed=feed, error=str(exc))
        return None


def _last_events_for_feed(feed: str) -> list[dict[str, Any]] | None:
    """Lit le dernier snapshot archivé pour ce feed (pour le --dedup)."""
    if not SNAPSHOTS_FILE.exists():
        return None
    last: list[dict[str, Any]] | None = None
    try:
        with SNAPSHOTS_FILE.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    snap = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if snap.get("feed") == feed:
                    last = snap.get("events")
    except OSError as exc:
        log.warning("forexfactory.dedup.read_error", error=str(exc))
        return None
    return last


def append_snapshot(feed: str, events: list[dict[str, Any]], dedup: bool) -> bool:
    """Ajoute un snapshot horodaté. Retourne True si écrit, False si skip (dedup)."""
    if dedup and _last_events_for_feed(feed) == events:
        log.info("forexfactory.snapshot.skipped_dedup", feed=feed, n_events=len(events))
        return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "feed": feed,
        "n_events": len(events),
        "events": events,
    }
    try:
        with SNAPSHOTS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.warning("forexfactory.snapshot.write_error", feed=feed, error=str(exc))
        return False
    log.info("forexfactory.snapshot.written", feed=feed, n_events=len(events))
    return True


def print_stats() -> None:
    """Affiche un résumé de l'archive accumulée (taille, snapshots, fenêtre)."""
    if not SNAPSHOTS_FILE.exists():
        print(f"Aucune archive à ce jour : {SNAPSHOTS_FILE} absent.")
        return
    n_lines = 0
    per_feed: dict[str, int] = {}
    first_ts: str | None = None
    last_ts: str | None = None
    with SNAPSHOTS_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                snap = json.loads(line)
            except json.JSONDecodeError:
                continue
            n_lines += 1
            feed = snap.get("feed", "?")
            per_feed[feed] = per_feed.get(feed, 0) + 1
            ts = snap.get("fetched_at")
            if ts:
                first_ts = first_ts or ts
                last_ts = ts
    size_kb = SNAPSHOTS_FILE.stat().st_size / 1024
    print(f"Archive : {SNAPSHOTS_FILE}")
    print(f"  snapshots : {n_lines}  ({size_kb:.1f} KB)")
    print(f"  par feed  : {per_feed}")
    print(f"  fenêtre   : {first_ts}  →  {last_ts}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archiveur SHADOW du calendrier macro ForexFactory (non wiré aux engines)."
    )
    parser.add_argument(
        "--feeds",
        nargs="+",
        default=["thisweek"],
        choices=sorted(FEED_URLS.keys()),
        help="Feeds à archiver (défaut et seul dispo : thisweek).",
    )
    parser.add_argument(
        "--dedup",
        action="store_true",
        help="Ne pas écrire si le snapshot est identique au précédent (même feed).",
    )
    parser.add_argument(
        "--stats", action="store_true", help="Afficher l'état de l'archive et sortir."
    )
    args = parser.parse_args()

    if args.stats:
        print_stats()
        return 0

    written = 0
    with httpx.Client() as client:
        for feed in args.feeds:
            events = fetch_feed(feed, client)
            if events is None:
                continue
            if append_snapshot(feed, events, dedup=args.dedup):
                written += 1

    print(f"ForexFactory archive : {written} snapshot(s) écrit(s) sur {len(args.feeds)} feed(s).")
    print_stats()
    return 0


if __name__ == "__main__":
    sys.exit(main())
