"""Scheduler standalone — lance les analyses swing et flash périodiquement.

Usage : `python -m tik_core.scripts.run_scheduler`

Dans un environnement prod, ce scheduler tourne comme un **process séparé**
(worker container) du process API. Pour le MVP local, on peut le lancer
dans le même container via docker-compose (scaling vertical suffisant).
"""

import asyncio
from datetime import datetime

import redis.asyncio as aioredis
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tik_core.config import get_settings
from tik_core.scoring.flash_engine import (
    analyze_flash_btc,
    read_last_emission,
    record_emission,
    should_emit,
)
from tik_core.scoring.hypothesis_generator import (
    HypothesisGenerator,
    build_hypothesis_generator,
)
from tik_core.scoring.publisher import publish_flash_signal, publish_swing_signal
from tik_core.scoring.source_credibility import recalibrate_sources
from tik_core.scoring.swing_engine import analyze_swing_btc, analyze_swing_gold

log = structlog.get_logger()


async def _run_swing_btc(
    session_maker, redis, hypothesis_generator: HypothesisGenerator | None
) -> None:
    try:
        if hypothesis_generator is not None:
            hypothesis_generator.reset_batch()
        decision = await analyze_swing_btc(
            redis=redis, hypothesis_generator=hypothesis_generator
        )
        async with session_maker() as session:
            await publish_swing_signal(session, redis, decision)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.error("scheduler.swing_btc.error", error=str(exc))


async def _run_swing_gold(
    session_maker, redis, fred_api_key,
    hypothesis_generator: HypothesisGenerator | None,
) -> None:
    try:
        if hypothesis_generator is not None:
            hypothesis_generator.reset_batch()
        decision = await analyze_swing_gold(
            fred_api_key=fred_api_key, redis=redis,
            hypothesis_generator=hypothesis_generator,
        )
        async with session_maker() as session:
            await publish_swing_signal(session, redis, decision)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.error("scheduler.swing_gold.error", error=str(exc))


async def _run_recalibrate_sources(session_maker, redis) -> None:
    """Recalibration daily des scores de crédibilité par source (ADR-011)."""
    try:
        results = await recalibrate_sources(session_maker, redis)
        log.info("scheduler.recalibrate_sources.done", n=len(results))
    except Exception as exc:  # noqa: BLE001
        log.error("scheduler.recalibrate_sources.error", error=str(exc))


async def _run_flash_btc(
    session_maker, redis, hypothesis_generator: HypothesisGenerator | None
) -> None:
    try:
        if hypothesis_generator is not None:
            hypothesis_generator.reset_batch()
        decision = await analyze_flash_btc(
            redis=redis, hypothesis_generator=hypothesis_generator
        )

        # Skip si données stale (l'engine a renvoyé confidence=0 + hypothesis explicite)
        if decision.confidence == 0.0 and "stale" in decision.hypothesis.lower():
            log.info("scheduler.flash_btc.skipped_stale_feed")
            return

        last = await read_last_emission(redis, decision.entity_id)
        if not should_emit(decision, last, datetime.utcnow()):
            log.info(
                "scheduler.flash_btc.skipped_no_change",
                direction=decision.direction,
            )
            return

        async with session_maker() as session:
            await publish_flash_signal(session, redis, decision)
            await session.commit()
        await record_emission(redis, decision.entity_id, decision)
    except Exception as exc:  # noqa: BLE001
        log.error("scheduler.flash_btc.error", error=str(exc))


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    # Construit le hypothesis_generator au démarrage (cf. ADR-012). Si
    # llm_hypothesis="template" ou Ollama indisponible, fallback sur
    # TemplateHypothesisGenerator — l'appel reste cheap et inoffensif.
    hypothesis_generator = await build_hypothesis_generator(
        generator_type=settings.llm_hypothesis,
        ollama_url=settings.ollama_url,
        ollama_model=settings.ollama_model,
    )
    log.info(
        "scheduler.hypothesis_generator_ready",
        method=getattr(hypothesis_generator, "method_name", "unknown"),
        mode=settings.llm_hypothesis_mode,
    )

    scheduler = AsyncIOScheduler()

    # Swing BTC : toutes les 15 min
    scheduler.add_job(
        _run_swing_btc,
        "interval",
        minutes=15,
        args=[session_maker, redis, hypothesis_generator],
        id="swing_btc",
        max_instances=1,
        coalesce=True,
    )
    # Swing Gold : toutes les 30 min (Yahoo est plus lent, moins besoin)
    scheduler.add_job(
        _run_swing_gold,
        "interval",
        minutes=30,
        args=[session_maker, redis, settings.fred_api_key, hypothesis_generator],
        id="swing_gold",
        max_instances=1,
        coalesce=True,
    )
    # Flash BTC : toutes les 5 min (émission conditionnelle gérée dans le job)
    scheduler.add_job(
        _run_flash_btc,
        "interval",
        minutes=5,
        args=[session_maker, redis, hypothesis_generator],
        id="flash_btc",
        max_instances=1,
        coalesce=True,
    )
    # Recalibration scores sources : daily 03:00 UTC (ADR-011)
    scheduler.add_job(
        _run_recalibrate_sources,
        "cron",
        hour=3,
        minute=0,
        args=[session_maker, redis],
        id="recalibrate_sources",
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    log.info("scheduler.started", jobs=[j.id for j in scheduler.get_jobs()])

    # Premier run immédiat
    await _run_swing_btc(session_maker, redis, hypothesis_generator)
    await _run_swing_gold(session_maker, redis, settings.fred_api_key, hypothesis_generator)
    await _run_flash_btc(session_maker, redis, hypothesis_generator)

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler.stopping")
        scheduler.shutdown()
        await hypothesis_generator.aclose()
        await redis.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
