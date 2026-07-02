"""Rétention DB — purge quotidienne des lignes au-delà de la profondeur choisie.

Décision utilisatrice 2026-07-02 (audit S-1 : croissance non bornée du disque) :
- **12 mois** pour les signaux (et leur historique de crédibilité) — assez pour
  tous les backtests saisonniers ;
- **3 mois** pour les titres de presse (`headlines`) — la table dupliquait
  chaque titre à chaque cycle de 30 min (dédup à l'insertion explicitement
  absente, cf. headlines_repo), c'est elle qui gonflait le plus vite ;
- **12 mois** pour les événements macro passés (table d'audit) ;
- **JAMAIS purgés** : `manual_trades` (le journal de la trader est précieux et
  minuscule), `entities`, `sources`, `api_keys`, `backtest_runs` (petits et
  utiles à l'historique des mesures).

Les feedbacks liés aux signaux purgés partent avec eux (suppression explicite
avant les signaux — ne dépend pas du ON DELETE CASCADE, absent du schéma
`create_all` des environnements de test).

Choix DELETE simple plutôt que `drop_chunks` Timescale : la volumétrie
(~200-300 signaux/jour) reste très loin du seuil où le DELETE ferait mal, et
le job tourne à 04:30 UTC (heure creuse). À reconsidérer si la volumétrie
explose (alors : politique de rétention native Timescale).
"""

from datetime import timedelta

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tik_core.storage.models import (
    Feedback,
    HeadlineRecord,
    MacroEvent,
    Signal,
    SourceCredibilityHistory,
)
from tik_core.utils.time import now_utc_naive

log = structlog.get_logger()

# Profondeurs de rétention (décision utilisatrice 2026-07-02) — en jours.
RETENTION_SIGNALS_DAYS = 365
RETENTION_HEADLINES_DAYS = 90
RETENTION_MACRO_EVENTS_DAYS = 365
RETENTION_CREDIBILITY_DAYS = 365


async def purge_expired_rows(session_maker: async_sessionmaker) -> dict[str, int]:
    """Supprime les lignes au-delà de la rétention. Retourne les comptes.

    Best-effort : toute erreur remonte au caller (le job scheduler l'attrape
    et loggue — un échec de purge n'est jamais bloquant, on retentera demain).
    """
    now = now_utc_naive()
    signals_cutoff = now - timedelta(days=RETENTION_SIGNALS_DAYS)
    headlines_cutoff = now - timedelta(days=RETENTION_HEADLINES_DAYS)
    macro_cutoff = now - timedelta(days=RETENTION_MACRO_EVENTS_DAYS)
    credibility_cutoff = now - timedelta(days=RETENTION_CREDIBILITY_DAYS)

    counts: dict[str, int] = {}
    async with session_maker() as session:
        # 1. Feedbacks des signaux qui vont partir (avant les signaux : ne
        #    dépend pas du CASCADE, absent du schéma de test create_all).
        old_signal_ids = select(Signal.id).where(Signal.timestamp < signals_cutoff)
        res = await session.execute(delete(Feedback).where(Feedback.signal_id.in_(old_signal_ids)))
        counts["feedbacks"] = res.rowcount or 0

        res = await session.execute(delete(Signal).where(Signal.timestamp < signals_cutoff))
        counts["signals"] = res.rowcount or 0

        res = await session.execute(
            delete(HeadlineRecord).where(HeadlineRecord.fetched_at < headlines_cutoff)
        )
        counts["headlines"] = res.rowcount or 0

        res = await session.execute(
            delete(MacroEvent).where(MacroEvent.scheduled_for < macro_cutoff)
        )
        counts["macro_events"] = res.rowcount or 0

        res = await session.execute(
            delete(SourceCredibilityHistory).where(
                SourceCredibilityHistory.computed_at < credibility_cutoff
            )
        )
        counts["source_credibility_history"] = res.rowcount or 0

        await session.commit()

    log.info("retention.purge.done", **counts)
    return counts
