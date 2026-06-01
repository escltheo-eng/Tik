"""Scheduler standalone — lance les analyses swing et flash périodiquement.

Usage : `python -m tik_core.scripts.run_scheduler`

Dans un environnement prod, ce scheduler tourne comme un **process séparé**
(worker container) du process API. Pour le MVP local, on peut le lancer
dans le même container via docker-compose (scaling vertical suffisant).
"""

import asyncio
import signal

import redis.asyncio as aioredis
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tik_core.config import get_settings
from tik_core.notify.alerts import check_and_alert
from tik_core.notify.briefing import send_briefing
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
from tik_core.scoring.macro_proximity import annotate_near_macro_event
from tik_core.scoring.publisher import publish_flash_signal, publish_swing_signal
from tik_core.scoring.source_credibility import recalibrate_sources
from tik_core.scoring.swing_engine import analyze_swing_btc, analyze_swing_gold
from tik_core.utils.time import now_utc

log = structlog.get_logger()


async def _run_swing_btc(
    session_maker, redis, hypothesis_generator: HypothesisGenerator | None
) -> None:
    try:
        if hypothesis_generator is not None:
            hypothesis_generator.reset_batch()
        decision = await analyze_swing_btc(redis=redis, hypothesis_generator=hypothesis_generator)
        async with session_maker() as session:
            # Flag discipline ±4h autour d'un event macro HIGH (best-effort,
            # ne touche pas direction/conviction/veracity — cf. macro_proximity).
            await annotate_near_macro_event(session, decision)
            await publish_swing_signal(session, redis, decision)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.error("scheduler.swing_btc.error", error=str(exc))


async def _run_swing_gold(
    session_maker,
    redis,
    fred_api_key,
    hypothesis_generator: HypothesisGenerator | None,
) -> None:
    try:
        if hypothesis_generator is not None:
            hypothesis_generator.reset_batch()
        decision = await analyze_swing_gold(
            fred_api_key=fred_api_key,
            redis=redis,
            hypothesis_generator=hypothesis_generator,
        )
        async with session_maker() as session:
            # Flag discipline ±4h autour d'un event macro HIGH (best-effort,
            # ne touche pas direction/conviction/veracity — cf. macro_proximity).
            await annotate_near_macro_event(session, decision)
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
        decision = await analyze_flash_btc(redis=redis, hypothesis_generator=hypothesis_generator)

        # Skip si données stale (l'engine a renvoyé confidence=0 + hypothesis explicite)
        if decision.confidence == 0.0 and "stale" in decision.hypothesis.lower():
            log.info("scheduler.flash_btc.skipped_stale_feed")
            return

        last = await read_last_emission(redis, decision.entity_id)
        if not should_emit(decision, last, now_utc()):
            log.info(
                "scheduler.flash_btc.skipped_no_change",
                direction=decision.direction,
            )
            return

        async with session_maker() as session:
            # Flag discipline ±4h autour d'un event macro HIGH (best-effort).
            await annotate_near_macro_event(session, decision)
            await publish_flash_signal(session, redis, decision)
            await session.commit()
        await record_emission(redis, decision.entity_id, decision)
    except Exception as exc:  # noqa: BLE001
        log.error("scheduler.flash_btc.error", error=str(exc))


async def _run_briefing(session_maker, redis) -> None:
    """Briefing du matin/midi/soir via Telegram (best-effort, ne lève jamais).

    `send_briefing` est déjà best-effort (skip propre si token/chat_id absents
    dans .env) ; le try ici est une ceinture+bretelles cohérente avec les
    autres jobs.
    """
    try:
        await send_briefing(session_maker, redis)
    except Exception as exc:  # noqa: BLE001
        log.error("scheduler.briefing.error", error=str(exc))


async def _run_alerts(session_maker, redis) -> None:
    """Alertes événements (choc prix BTC + macro imminent) — best-effort.

    `check_and_alert` ne lève jamais et gère son propre anti-spam Redis ; le try
    ici est une ceinture+bretelles cohérente avec les autres jobs.
    """
    try:
        await check_and_alert(session_maker, redis)
    except Exception as exc:  # noqa: BLE001
        log.error("scheduler.alerts.error", error=str(exc))


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    # Construit le hypothesis_generator au démarrage (cf. ADR-012). Si
    # llm_hypothesis="template" ou Ollama indisponible, fallback sur
    # TemplateHypothesisGenerator — l'appel reste cheap et inoffensif.
    #
    # Lock partagé : filet de sécurité pour sérialiser les appels HTTP Ollama
    # entre jobs (au cas où). Fix A1 (audit 2026-05-31) en 3 temps :
    #   1. LLM réservé au SWING (flash exclu, cf. add_job flash_btc).
    #   2. keep_alive=24h (hypothesis_generator) → modèle reste chaud.
    #   3. swing_btc (:00/:15/:30/:45) et swing_gold (:10/:40) sur des minutes
    #      cron DISJOINTES → ils ne collisionnent JAMAIS, donc le Lock n'est en
    #      pratique plus contesté (chaque swing tourne seul, modèle chaud, sur
    #      4 cœurs CPU sans GPU). Mesure post-(1)+(2) : ollama_error 95/24h→1,
    #      mais 36 % de swings encore en template à cause de la collision
    #      swing↔swing (budget wait_for 60 s mangé par l'attente du Lock) →
    #      résolu par le décalage cron (3).
    ollama_lock = asyncio.Lock()
    hypothesis_generator = await build_hypothesis_generator(
        generator_type=settings.llm_hypothesis,
        ollama_url=settings.ollama_url,
        ollama_model=settings.ollama_model,
        lock=ollama_lock,
    )
    log.info(
        "scheduler.hypothesis_generator_ready",
        method=getattr(hypothesis_generator, "method_name", "unknown"),
        mode=settings.llm_hypothesis_mode,
        ollama_lock_enabled=True,
    )

    scheduler = AsyncIOScheduler()

    # Swing BTC : toutes les 15 min, minutes FIXES :00/:15/:30/:45 (cron).
    # Fix A1 complétion (2026-05-31) : minutes DISJOINTES de swing_gold (:10/:40)
    # pour éliminer la collision Ollama qui faisait timeout ~1 swing sur 2 aux
    # ticks partagés (:23/:53 en interval). Chaque swing tourne désormais seul
    # avec le modèle chaud → swing ≈100 % LLM au lieu de 64 %.
    scheduler.add_job(
        _run_swing_btc,
        "cron",
        minute="0,15,30,45",
        args=[session_maker, redis, hypothesis_generator],
        id="swing_btc",
        max_instances=1,
        coalesce=True,
    )
    # Swing Gold : toutes les 30 min aux minutes :10/:40 (cron) — décalé de
    # swing_btc (fix A1 complétion : évite la collision Ollama, cf. ci-dessus).
    scheduler.add_job(
        _run_swing_gold,
        "cron",
        minute="10,40",
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
        # Fix A1 : flash exclu du LLM (None) → hypothèse template instantanée.
        # Le flash (5 min) est du bruit sans edge (Paquet 43) et était la
        # principale source de contention Ollama. LLM réservé au swing.
        args=[session_maker, redis, None],
        id="flash_btc",
        max_instances=1,
        coalesce=True,
    )
    # Recalibration scores sources : daily 03:00 UTC (ADR-011)
    # misfire_grace_time=86400s (24h) : si le scheduler est restart entre
    # 03:00 et 02:59 le lendemain, le run manqué est rattrapé. Sans ça,
    # APScheduler skip le run et la recalibration ne tourne jamais (cf
    # bug observé 2026-05-07 : 0 entries DB depuis le déploiement Paquet 5).
    scheduler.add_job(
        _run_recalibrate_sources,
        "cron",
        hour=3,
        minute=0,
        args=[session_maker, redis],
        id="recalibrate_sources",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=86400,
    )

    # Briefing Telegram : 3×/jour aux heures UTC les plus utiles pour suivre BTC.
    #   06:00 UTC ≈ 08h Paris  → matin Europe (résume la nuit asiatique)
    #   13:00 UTC ≈ 09h New York → matin/ouverture US (la session qui bouge le +)
    #   20:00 UTC ≈ 22h Paris / clôture actions US → bilan de journée
    # Best-effort : skip propre si TIK_TELEGRAM_* absents du .env. PAS de run au
    # boot (sinon spam à chaque redéploiement du scheduler).
    scheduler.add_job(
        _run_briefing,
        "cron",
        hour="6,13,20",
        minute=0,
        args=[session_maker, redis],
        id="briefing",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # Alertes événements : toutes les 15 min (choc prix BTC + macro imminent).
    # Anti-spam géré dans check_and_alert (ancre Redis + set events). PAS de run
    # au boot (évite une alerte à chaque redéploiement du scheduler).
    scheduler.add_job(
        _run_alerts,
        "interval",
        minutes=15,
        args=[session_maker, redis],
        id="alerts",
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    log.info("scheduler.started", jobs=[j.id for j in scheduler.get_jobs()])

    # Premier run immédiat
    await _run_swing_btc(session_maker, redis, hypothesis_generator)
    await _run_swing_gold(session_maker, redis, settings.fred_api_key, hypothesis_generator)
    await _run_flash_btc(session_maker, redis, None)  # flash = template (fix A1)
    # Recalibration au boot : garantit qu'au moins 1× / déploiement, les
    # scores sont rafraîchis. Idempotent (ré-écrit les mêmes scores si
    # tourné le même jour). Combiné au misfire_grace_time, couvre tous
    # les cas de restart Docker fréquents.
    await _run_recalibrate_sources(session_maker, redis)

    # Arrêt gracieux : capte SIGTERM (Docker stop) + SIGINT (Ctrl-C). Avant
    # l'audit 2026-05-24 (B1), seul KeyboardInterrupt/SystemExit était capté —
    # SIGTERM tuait le process sans fermer scheduler/redis/engine proprement.
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(_sig, stop_event.set)
        except NotImplementedError:  # plateforme non-Unix
            pass
    try:
        await stop_event.wait()
    finally:
        log.info("scheduler.stopping")
        scheduler.shutdown()
        await hypothesis_generator.aclose()
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
