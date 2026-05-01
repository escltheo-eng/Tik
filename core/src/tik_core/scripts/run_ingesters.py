"""Runner standalone pour les ingesters marché et macro.

Usage : `python -m tik_core.scripts.run_ingesters`
"""

import asyncio

import redis.asyncio as aioredis
import structlog

from tik_core.aggregator.binance_ingester import BinanceTradesIngester
from tik_core.aggregator.cftc_cot_ingester import CftcCotIngester
from tik_core.aggregator.cryptocompare_ingester import CryptoCompareIngester
from tik_core.aggregator.fear_greed_ingester import FearGreedIngester
from tik_core.aggregator.fred_ingester import FredIngester
from tik_core.aggregator.google_news_ingester import GoogleNewsIngester
from tik_core.aggregator.news_classifier import build_news_classifier
from tik_core.aggregator.reddit_ingester import RedditIngester
from tik_core.aggregator.yahoo_ingester import YahooPoller
from tik_core.config import get_settings

log = structlog.get_logger()


async def main() -> None:
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

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
        ),
        build_news_classifier(
            classifier_type=settings.news_classifier,
            ollama_url=settings.ollama_url,
            ollama_model=settings.ollama_model,
            asset_name="Bitcoin",
        ),
        build_news_classifier(
            classifier_type=settings.news_classifier,
            ollama_url=settings.ollama_url,
            ollama_model=settings.ollama_model,
            asset_name="Gold",
        ),
        build_news_classifier(
            classifier_type=settings.news_classifier,
            ollama_url=settings.ollama_url,
            ollama_model=settings.ollama_model,
            asset_name="Bitcoin",
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
        ),
        GoogleNewsIngester(
            redis,
            classifier=gn_btc_classifier,
            entity_id="BTC",
            query="Bitcoin",
            interval_s=1800,
            limit=50,
        ),
        GoogleNewsIngester(
            redis,
            classifier=gn_gold_classifier,
            entity_id="GOLD",
            query='"gold price"',
            interval_s=1800,
            limit=50,
        ),
        RedditIngester(
            redis,
            classifier=red_btc_classifier,
            entity_id="BTC",
            subreddits=["Bitcoin", "CryptoMarkets"],
            interval_s=1800,
            limit_per_sub=50,
        ),
        CftcCotIngester(redis, interval_s=24 * 3600),
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


if __name__ == "__main__":
    asyncio.run(main())
