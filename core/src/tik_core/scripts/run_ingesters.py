"""Runner standalone pour les ingesters marché et macro.

Usage : `python -m tik_core.scripts.run_ingesters`
"""

import asyncio

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tik_core.aggregator.binance_ingester import BinanceTradesIngester
from tik_core.aggregator.cftc_cot_ingester import CftcCotIngester
from tik_core.aggregator.cryptocompare_ingester import CryptoCompareIngester
from tik_core.aggregator.fear_greed_ingester import FearGreedIngester
from tik_core.aggregator.fred_calendar_ingester import FredCalendarIngester
from tik_core.aggregator.fred_ingester import FredIngester
from tik_core.aggregator.gdelt_ingester import GdeltIngester
from tik_core.aggregator.google_news_ingester import GoogleNewsIngester
from tik_core.aggregator.macro_static_ingester import MacroStaticIngester
from tik_core.aggregator.news_classifier import build_news_classifier
from tik_core.aggregator.polymarket_ingester import PolymarketIngester
from tik_core.aggregator.reddit_ingester import RedditIngester
from tik_core.aggregator.yahoo_ingester import YahooPoller
from tik_core.config import get_settings

log = structlog.get_logger()


async def main() -> None:
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    # Engine + session_maker dédiés aux ingesters (Lacune A J+10).
    # Persistance DB des titres bruts pour audit historique. Séparé du
    # session_maker du core (qui est dans l'autre process), donc pas de
    # conflit de pool. Pool size modeste : 3 ingesters × ~1 INSERT par
    # cycle de 30 min = très peu de connexions concurrentes.
    db_engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
    )
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)

    # ADR-008/009 — un classifier par ingester pour isoler les circuit breakers
    # Ollama. Construits en parallèle (4 pings simultanés) pour économiser
    # ~3 s au boot vs construction séquentielle.
    (
        cc_btc_classifier,
        gn_btc_classifier,
        gn_gold_classifier,
        red_btc_classifier,
    ) = await asyncio.gather(
        build_news_classifier(
            classifier_type=settings.news_classifier,
            ollama_url=settings.ollama_url,
            ollama_model=settings.ollama_model,
            asset_name="Bitcoin",
            redis=redis,
        ),
        build_news_classifier(
            classifier_type=settings.news_classifier,
            ollama_url=settings.ollama_url,
            ollama_model=settings.ollama_model,
            asset_name="Bitcoin",
            redis=redis,
        ),
        build_news_classifier(
            classifier_type=settings.news_classifier,
            ollama_url=settings.ollama_url,
            ollama_model=settings.ollama_model,
            asset_name="Gold",
            redis=redis,
        ),
        build_news_classifier(
            classifier_type=settings.news_classifier,
            ollama_url=settings.ollama_url,
            ollama_model=settings.ollama_model,
            asset_name="Bitcoin",
            redis=redis,
        ),
    )

    ingesters = [
        BinanceTradesIngester(redis, symbol="btcusdt", entity_id="BTC"),
        YahooPoller(redis, symbol="GC=F", entity_id="GOLD", interval_s=60),
        FredIngester(redis, api_key=settings.fred_api_key, interval_s=3600),
        FearGreedIngester(redis, interval_s=3600),
        CryptoCompareIngester(
            redis,
            api_key=settings.cryptocompare_api_key,
            classifier=cc_btc_classifier,
            currency="BTC",
            interval_s=3600,
            session_maker=session_maker,
        ),
        GoogleNewsIngester(
            redis,
            classifier=gn_btc_classifier,
            entity_id="BTC",
            query="Bitcoin",
            interval_s=1800,
            limit=50,
            session_maker=session_maker,
        ),
        GoogleNewsIngester(
            redis,
            classifier=gn_gold_classifier,
            entity_id="GOLD",
            query='"gold price"',
            interval_s=1800,
            limit=50,
            session_maker=session_maker,
        ),
        RedditIngester(
            redis,
            classifier=red_btc_classifier,
            entity_id="BTC",
            subreddits=["Bitcoin", "CryptoMarkets"],
            interval_s=1800,
            limit_per_sub=50,
            session_maker=session_maker,
        ),
        # ADR-010 — pas de classifier injecté : GDELT consomme le tone brut
        # calculé par GDELT (NLP scientifique non-LLM), première source de
        # diversification méthodologique pure dans le pipeline.
        GdeltIngester(
            redis,
            entity_id="GOLD",
            query='"gold price"',
            timespan="1d",
            lang="eng",
            interval_s=1800,
        ),
        CftcCotIngester(redis, interval_s=24 * 3600),
        # Lacune B Phase B1 J+10 — FRED Releases dynamiques (ADR-017).
        # Polling daily des release_dates FRED (NFP, CPI, PPI, GDP…).
        # Skip si pas de clé FRED (Phase B2 : ne bloque plus FOMC static
        # qui est désormais géré par MacroStaticIngester).
        FredCalendarIngester(
            api_key=settings.fred_api_key,
            session_maker=session_maker,
            interval_s=24 * 3600,
        ),
        # Lacune B Phase B2 — Calendrier macro statique multi-banques (ADR-020).
        # Upsert daily des dates FOMC + ECB + BoJ + BoE depuis macro_calendar_data.
        # Aucune dépendance externe (pas de clé API). Tourne même sans FRED.
        MacroStaticIngester(
            session_maker=session_maker,
            interval_s=24 * 3600,
        ),
        # Polymarket — marchés prédictifs BTC, MODE SHADOW (backlog-osint 2026-05-24).
        # Collecte les probas implicites dans Redis SANS brancher sur le
        # combined_bias (aucun _enrich_with_polymarket). But : historique pour
        # mesurer la valeur prédictive avant tout enrôlement. Retrait = retirer
        # cette ligne.
        PolymarketIngester(redis, interval_s=3600),
    ]

    for ing in ingesters:
        await ing.start()

    log.info("ingesters.started", count=len(ingesters))

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        log.info("ingesters.stopping")
        for ing in ingesters:
            await ing.stop()
        await redis.close()
        await db_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
