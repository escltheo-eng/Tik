"""Helper d'insertion et de lecture des titres OSINT bruts (Lacune A J+10).

Stocke les titres bruts dans la table `headlines` aux côtés des agrégats
Redis (TTL 2 h). Permet la retro-analyse, la mesure de qualité du classifier
sur le temps long, et la convergence vers le standard OSINT pro.

Le helper est best-effort : si l'écriture DB échoue, on log un warning mais
on ne bloque pas l'ingester (cohérent avec le pattern resilience par sub
Reddit, etc.).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tik_core.storage.models import HeadlineRecord
from tik_core.utils.time import now_utc_naive

log = structlog.get_logger()


def compute_title_hash(title: str) -> str:
    """SHA-256 du titre normalisé (strip + lowercase), tronqué à 16 hex chars.

    Cohérent avec le hash utilisé pour le cache Redis du sentiment (Lacune C)
    afin que la même normalisation s'applique partout (même clé cache, même
    clé dédup historique).
    """
    normalized = title.strip().lower().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:16]


def parse_iso_naive(value: Any) -> datetime | None:
    """Parse une string ISO 8601 en datetime **naïf** UTC.

    Cohérent avec le workaround Bug 9 / `publisher.py:_publish_signal` :
    les colonnes DB sont en `TIMESTAMP WITHOUT TIMEZONE`, asyncpg refuse
    les datetime aware → on strip la tzinfo avant insertion.

    Tolère :
    - Suffixe `Z` (forme courte UTC)
    - Suffixe `+HH:MM` ou autre offset explicite (converti en UTC puis strippé)
    - Naïf (renvoyé tel quel)
    - Objet `datetime` déjà parsé
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value
    try:
        s = str(value)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC).replace(tzinfo=None)
        return dt
    except (TypeError, ValueError):
        return None


def _build_record(
    entity_id: str,
    source: str,
    credibility: float,
    headline: dict[str, Any],
) -> HeadlineRecord | None:
    """Convertit un dict headline en `HeadlineRecord`. Retourne None si invalide."""
    title = str(headline.get("title") or "").strip()
    if not title:
        return None
    fetched_at = parse_iso_naive(headline.get("fetched_at")) or now_utc_naive()
    published_at = parse_iso_naive(headline.get("published_at"))
    return HeadlineRecord(
        entity_id=entity_id,
        source=source,
        title_hash=compute_title_hash(title),
        title=title,
        url=headline.get("url"),
        publisher=str(headline.get("publisher") or "unknown"),
        sentiment=str(headline.get("sentiment") or "neutral"),
        credibility=credibility,
        published_at=published_at,
        fetched_at=fetched_at,
    )


async def persist_headlines(
    session_maker: async_sessionmaker[AsyncSession] | None,
    entity_id: str,
    source: str,
    credibility: float,
    headlines: list[dict[str, Any]],
) -> int:
    """Insère N titres dans la table `headlines`. Retourne le nombre inséré.

    **Best-effort** : si l'écriture DB échoue (Postgres down, contention,
    etc.), on log un warning et on retourne 0 — l'ingester continue son
    cycle. Aucune exception remontée.

    Si `session_maker` est `None`, on ne persiste rien (rétrocompat avec
    les ingesters qui n'ont pas reçu de session_maker).

    Dédup à l'insertion : aucune. On stocke chaque cycle même si le titre
    a déjà été ingéré 30 min avant. La dédup se fait au niveau lecture
    (endpoint `/headlines/history`) si nécessaire.
    """
    if session_maker is None or not headlines:
        return 0

    rows: list[HeadlineRecord] = []
    for h in headlines:
        if not isinstance(h, dict):
            continue
        record = _build_record(entity_id, source, credibility, h)
        if record is not None:
            rows.append(record)

    if not rows:
        return 0

    try:
        async with session_maker() as session:
            session.add_all(rows)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "headlines_repo.persist_error",
            entity_id=entity_id,
            source=source,
            n_rows=len(rows),
            error=str(exc),
        )
        return 0

    return len(rows)


async def fetch_headlines_history(
    session: AsyncSession,
    entity_id: str,
    since: datetime,
    limit: int,
    source: str | None = None,
) -> list[HeadlineRecord]:
    """Récupère les titres historiques d'une entity depuis `since`, triés DESC.

    Si `source` est fourni, filtre uniquement les titres de cette source.
    `limit` borne le nombre de résultats (0 < limit ≤ 500 attendu côté
    endpoint).
    """
    stmt = (
        select(HeadlineRecord)
        .where(HeadlineRecord.entity_id == entity_id)
        .where(HeadlineRecord.fetched_at >= since)
        .order_by(HeadlineRecord.fetched_at.desc())
        .limit(limit)
    )
    if source is not None:
        stmt = stmt.where(HeadlineRecord.source == source)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def cutoff_from_hours(hours: int) -> datetime:
    """Calcule le cutoff (datetime naïf UTC) pour une fenêtre de N heures."""
    return now_utc_naive() - timedelta(hours=hours)
