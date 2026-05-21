"""Reset des scores de crédibilité dynamiques (Redis) — R2/R6, Paquet 34.

Efface les clés ``tik.source_credibility.<source>`` pour que l'affichage des
signaux (champ ``evidence[].score``) revienne aux scores STATIQUES de
``SOURCE_SCORES`` au lieu des scores pénalisés sur données pré-fix contaminées
(cf. CLAUDE.md Paquet 33 Découverte n°1 + audit-dual-lens R2/R6).

La recalibration corrigée (cf. ``RECALIBRATION_DATA_FLOOR`` dans
``source_credibility.py``) ne ré-écrira ces clés qu'à partir de données propres
ET mûres (~2026-05-22+).

Usage :
    docker exec tik-core python -m tik_core.scripts.reset_source_credibility

Sécurité : N'efface QUE les clés EXACTES de ``RECALIBRATABLE_SOURCES``. Aucune
autre clé Redis (last_price, sentiment cache, flash direction, etc.), aucune
donnée Postgres, aucun signal n'est touché. Pas de wildcard, pas de FLUSHDB.
"""

from __future__ import annotations

import asyncio

import redis.asyncio as aioredis
import structlog

from tik_core.config import get_settings
from tik_core.scoring.source_credibility import (
    RECALIBRATABLE_SOURCES,
    REDIS_KEY_TPL,
)

log = structlog.get_logger()


async def reset_source_credibility() -> dict[str, str]:
    """DELETE les clés de crédibilité dynamique.

    Retourne un rapport ``{source: "deleted" | "absent"}``.
    """
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    report: dict[str, str] = {}
    try:
        for source in sorted(RECALIBRATABLE_SOURCES):
            key = REDIS_KEY_TPL.format(source=source)
            deleted = await redis.delete(key)
            report[source] = "deleted" if deleted else "absent"
            log.info(
                "reset_source_credibility.key",
                source=source,
                result=report[source],
            )
    finally:
        await redis.aclose()
    return report


def main() -> None:
    report = asyncio.run(reset_source_credibility())
    n_deleted = sum(1 for v in report.values() if v == "deleted")
    print(f"Reset terminé : {n_deleted} clé(s) supprimée(s) sur {len(report)} sources.")
    for source, result in sorted(report.items()):
        print(f"  {source}: {result}")


if __name__ == "__main__":
    main()
