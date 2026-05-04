"""Endpoint headlines : titres bruts OSINT agrégés multi-source.

Phase 1 du plan trading manuel J+10 (cf. `docs/backlog.md` entry n°3).

Lit les payloads Redis publiés par les ingesters news (Google News,
CryptoCompare, Reddit) et retourne une liste fusionnée des derniers
titres bruts cités par leurs sources, triée par crédibilité × récence.

Pattern OSINT pro : zéro synthèse LLM, zéro hallucination — uniquement
de la donnée déjà classifiée au moment de l'ingestion.

Endpoint **domain-agnostic** : `entity_id` est passé tel quel, l'endpoint
fonctionne pour BTC, GOLD, mais aussi un futur match NBA, élection, etc.
tant que les ingesters publient sous la convention
`tik.sentiment.{source}.{entity}`.

Architecture : 3 helpers purs (`_parse_iso`, `_iter_headlines_from_payload`,
`_finalize_headlines`) testables sans Redis. L'endpoint orchestre la
lecture Redis et délègue la logique métier aux helpers.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from math import exp

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, Query

from tik_core.auth import AuthContext, require_scope
from tik_core.config import get_settings
from tik_core.scoring.source_credibility import get_effective_score
from tik_core.scoring.swing_engine import SOURCE_SCORES
from tik_core.storage.schemas import HeadlineOut
from tik_core.utils.time import now_utc

log = structlog.get_logger()

router = APIRouter(prefix="/headlines")

# Mapping source_id → template Redis key. Étendre ici quand un nouvel
# ingester news (Nitter, GDELT BTC, etc.) sera ajouté.
NEWS_SOURCE_KEYS: list[tuple[str, str]] = [
    ("google_news_rss", "tik.sentiment.google_news.{entity}"),
    ("cryptocompare_news", "tik.sentiment.cryptocompare.{entity}"),
    ("reddit_btc", "tik.sentiment.reddit.{entity}"),
]

# Half-life de 12 h pour la décroissance exponentielle de la récence.
# Choix : les news ont une demi-vie sentiment de quelques heures, mais
# pas si rapide qu'un titre de la veille soit invisible. 12 h donne un
# compromis qui laisse les titres de la nuit visibles le matin.
DECAY_HOURS = 12.0


def _parse_iso(value: object) -> datetime | None:
    """Parse une chaîne ISO 8601 (Z, +00:00 ou naïf) en datetime aware UTC.

    Tolère :
    - Suffixe `Z` (forme courte UTC)
    - Suffixe `+00:00` ou autre offset explicite
    - Naïf (considéré comme UTC sémantique)
    - Objet `datetime` déjà parsé (renvoyé après normalisation tz)
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    try:
        s = str(value)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _normalize_title(title: str) -> str:
    """Normalise un titre pour la dédup multi-source.

    Lowercase + trim — un même article relayé sur 2 sources différentes
    a généralement un titre identique au casing près. Pas de dédup
    fuzzy plus poussée pour l'instant (risque de masquer des titres
    légitimement différents).
    """
    return title.lower().strip()


def _sort_score(headline: dict, now: datetime, sort: str) -> float:
    """Calcule la clé de tri pour un titre.

    `credibility_recency` : crédibilité × exp(-age_h / DECAY_HOURS)
    `recency` : -age_h (le plus récent d'abord)

    L'âge est calculé depuis `published_at` si dispo (date réelle de
    publication de l'article), sinon depuis `fetched_at` (cycle Tik).
    """
    ref_dt = headline.get("published_at") or headline["fetched_at"]
    age_h = max(0.0, (now - ref_dt).total_seconds() / 3600.0)
    if sort == "recency":
        return -age_h
    decay = exp(-age_h / DECAY_HOURS)
    return headline["credibility"] * decay


def _iter_headlines_from_payload(
    payload: object,
    source_id: str,
    credibility: float,
    cutoff: datetime,
) -> list[dict]:
    """Extrait les headlines valides d'un payload Redis (déjà parsé en dict).

    Filtre celles dont :
    - `fetched_at` est manquant, invalide, ou < cutoff
    - `title` est vide après strip

    Tolère :
    - payload non-dict → liste vide
    - champ `headlines` absent ou non-list (rétrocompat avec payloads
      publiés AVANT cette feature) → liste vide
    - entries non-dict → ignorées silencieusement
    """
    if not isinstance(payload, dict):
        return []
    headlines = payload.get("headlines")
    if not isinstance(headlines, list):
        return []
    out: list[dict] = []
    for h in headlines:
        if not isinstance(h, dict):
            continue
        title = str(h.get("title") or "").strip()
        if not title:
            continue
        fetched_at = _parse_iso(h.get("fetched_at"))
        if fetched_at is None or fetched_at < cutoff:
            continue
        out.append(
            {
                "title": title,
                "url": h.get("url"),
                "publisher": str(h.get("publisher") or "unknown"),
                "source": source_id,
                "credibility": credibility,
                "sentiment": str(h.get("sentiment") or "neutral"),
                "published_at": _parse_iso(h.get("published_at")),
                "fetched_at": fetched_at,
            }
        )
    return out


def _finalize_headlines(
    merged: list[dict],
    sort: str,
    limit: int,
    now: datetime,
) -> list[dict]:
    """Trie + dédup par titre normalisé + cap à `limit`. Logique pure.

    Le tri est stable au sens Python — entre deux headlines de score
    identique, l'ordre d'insertion est préservé (ce qui matche l'ordre
    d'itération `NEWS_SOURCE_KEYS`).
    """
    if not merged:
        return []
    merged.sort(key=lambda h: _sort_score(h, now, sort), reverse=True)
    seen: set[str] = set()
    deduped: list[dict] = []
    for h in merged:
        key_norm = _normalize_title(h["title"])
        if key_norm in seen:
            continue
        seen.add(key_norm)
        deduped.append(h)
    return deduped[:limit]


@router.get("/{entity_id}", response_model=list[HeadlineOut])
async def get_top_headlines(
    entity_id: str,
    limit: int = Query(10, ge=1, le=50),
    since_hours: int = Query(24, ge=1, le=72),
    sort: str = Query(
        "credibility_recency",
        pattern="^(credibility_recency|recency)$",
    ),
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> list[HeadlineOut]:
    """Retourne les derniers titres bruts agrégés depuis les ingesters news.

    - `entity_id` : identifiant entity Tik (ex: `BTC`, `GOLD`). Domain-agnostic.
    - `limit` : nombre max de titres retournés (1-50, défaut 10).
    - `since_hours` : fenêtre temporelle (1-72h, défaut 24h).
    - `sort` : `credibility_recency` (défaut) ou `recency` pure.

    Réponse : liste de `HeadlineOut` triés desc par score de tri. Dédup
    par titre normalisé (lowercase trim) entre sources.

    Si aucun ingester n'a publié de titre dans la fenêtre, retourne `[]`
    (pas d'erreur). Les sources indisponibles sont silencieusement
    ignorées (résilience par source — cohérent avec le pattern overlay
    multi-source ADR-004).
    """
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        cutoff = now_utc() - timedelta(hours=since_hours)
        merged: list[dict] = []

        for source_id, key_tpl in NEWS_SOURCE_KEYS:
            key = key_tpl.format(entity=entity_id.lower())
            try:
                raw = await redis.get(key)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "headlines.redis_error",
                    entity_id=entity_id,
                    source=source_id,
                    error=str(exc),
                )
                continue
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                log.warning(
                    "headlines.payload_parse_error",
                    entity_id=entity_id,
                    source=source_id,
                )
                continue

            credibility = get_effective_score(source_id, SOURCE_SCORES)
            merged.extend(
                _iter_headlines_from_payload(payload, source_id, credibility, cutoff)
            )

        finalized = _finalize_headlines(merged, sort, limit, now_utc())
        return [HeadlineOut(**h) for h in finalized]
    finally:
        await redis.close()
