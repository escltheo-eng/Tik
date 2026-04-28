"""Scheduler standalone — lance les analyses swing périodiquement.

Usage : `python -m tik_core.scripts.run_scheduler`

Dans un environnement prod, ce scheduler tourne comme un **process séparé**
(worker container) du process API. Pour le MVP local, on peut le lancer
dans le même container via docker-compose (scaling vertical suffisant).
"""

import asyncio

import redis.asyncio as aioredis
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tik_core.config import get_settings
from tik_core.scoring.publisher import publish_swing_signal
from tik_core.scoring.swing_engine import analyze_swing_btc, analyze_swing_gold

log = structlog.get_logger()


async def _run_swing_btc(session_maker, redis) -> None:
    try:
        decision = await analyze_swing_btc(redis=redis)
        async with session_maker() as session:
            await publish_swing_signal(session, redis, decision)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.error("scheduler.swing_btc.error", error=str(exc))


async def _run_swing_gold(session_maker, redis, fred_api_key) -> None:
    try:
        decision = await analyze_swing_gold(fred_api_key=fred_api_key)
        async with session_maker() as session:
            await publish_swing_signal(session, redis, decision)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.error("scheduler.swing_gold.error", error=str(exc))


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    scheduler = AsyncIOScheduler()

    # Swing BTC : toutes les 15 min
    scheduler.add_job(
        _run_swing_btc,
        "interval",
        minutes=15,
        args=[session_maker, redis],
        id="swing_btc",
        max_instances=1,
        coalesce=True,
    )
    # Swing Gold : toutes les 30 min (Yahoo est plus lent, moins besoin)
    scheduler.add_job(
        _run_swing_gold,
        "interval",
        minutes=30,
        args=[session_maker, redis, settings.fred_api_key],
        id="swing_gold",
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    log.info("scheduler.started", jobs=[j.id for j in scheduler.get_jobs()])

    # Premier run immédiat
    await _run_swing_btc(session_maker, redis)
    await _run_swing_gold(session_maker, redis, settings.fred_api_key)

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler.stopping")
        scheduler.shutdown()
        await redis.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
