"""Runner standalone pour les ingesters marché et macro.

Usage : `python -m tik_core.scripts.run_ingesters`
"""

import asyncio
import signal

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tik_core.aggregator.binance_derivatives_ingester import BinanceDerivativesIngester
from tik_core.aggregator.binance_ingester import BinanceTradesIngester
from tik_core.aggregator.cftc_cot_ingester import CftcCotIngester
from tik_core.aggregator.coingecko_sentiment_ingester import CoinGeckoSentimentIngester
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
        # Polymarket — marchés prédictifs BTC + GOLD, MODE SHADOW (backlog-osint
        # 2026-05-24). Collecte les probas implicites dans Redis SANS brancher sur
        # le combined_bias (aucun _enrich_with_polymarket). But : historique pour
        # mesurer la valeur prédictive avant tout enrôlement + contexte de marché
        # pour le trader (GOLD ajouté 2026-05-28). Retrait = retirer ces lignes.
        PolymarketIngester(redis, entity="BTC", interval_s=3600),
        PolymarketIngester(redis, entity="GOLD", interval_s=3600),
        # CoinGecko sentiment communautaire BTC — MODE SHADOW (ADR-021).
        # Collecte le vote up/down dans Redis (+ historique cappé) SANS toucher
        # le combined_bias : l'overlay swing est gaté par
        # settings.coingecko_overlay_enabled (défaut False). But : mesurer la
        # divergence vs Fear & Greed avant enrôlement. Retrait = retirer cette
        # ligne. Candidat 4e overlay BTC suite ban IP Reddit (Bug 11).
        CoinGeckoSentimentIngester(redis, interval_s=3600),
        # Dérivés Binance (funding rate / open interest / ratio long-short retail
        # ET top traders) — MODE SHADOW (ADR-023). Collecte le POSITIONNEMENT
        # dérivés BTC dans Redis SANS toucher le combined_bias : il n'existe
        # AUCUN _enrich_with_binance_derivatives ni toggle (zéro ligne touchée
        # dans les moteurs). But : famille de données DIFFÉRENTE du sentiment
        # retardé, à mesurer (measure_btc_derivatives.py) avant tout enrôlement
        # ≥ 2 semaines. Retrait = retirer cette ligne. Connectivité futures
        # vérifiée depuis le VPS le 2026-06-03 (HTTP 200 sur tous les endpoints).
        BinanceDerivativesIngester(redis, entity="BTC", interval_s=3600),
    ]

    for ing in ingesters:
        await ing.start()

    log.info("ingesters.started", count=len(ingesters))

    # Arrêt gracieux : capte SIGTERM (Docker stop) + SIGINT. Avant l'audit
    # 2026-05-24 (B1), SIGTERM tuait le process sans stop() des ingesters ni
    # fermeture de redis/engine.
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
        log.info("ingesters.stopping")
        for ing in ingesters:
            await ing.stop()
        await redis.aclose()
        await db_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
