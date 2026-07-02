"""Tests de robustesse des boucles d'ingesters (audit 2026-07-02, chantier T3).

Couvre les trois constats de l'audit sur les 8 ingesters « anciens » :

1. Écritures Redis protégées : une `redis.exceptions.ConnectionError` au
   setex/publish ne doit PAS tuer la boucle `_run` — l'ingester log un warning
   et retente au cycle suivant (avant le fix, la task mourait en silence).
2. Supervision des tasks : `supervise_task` logge `ingester.task_died` quand
   la boucle meurt sur exception (et rien sur une annulation normale).
3. `stop()` robuste : une task déjà morte re-lève son exception au `await` —
   stop() la capte au lieu de la propager (sinon l'arrêt gracieux de
   run_ingesters s'interrompait au premier ingester fautif).

Sans réseau, sans Redis réel, sans DB : fetch mockés + mock Redis en panne.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import redis.exceptions
from structlog.testing import capture_logs

from tik_core.aggregator.base import MacroDataPoint, MarketTick
from tik_core.aggregator.cftc_cot_ingester import CftcCotIngester
from tik_core.aggregator.cryptocompare_ingester import CryptoCompareIngester
from tik_core.aggregator.fear_greed_ingester import FearGreedIngester
from tik_core.aggregator.fred_ingester import MACRO_LAST_TTL_S, FredIngester
from tik_core.aggregator.gdelt_ingester import GdeltIngester
from tik_core.aggregator.google_news_ingester import GoogleNewsIngester
from tik_core.aggregator.news_classifier import NewsClassifier
from tik_core.aggregator.reddit_ingester import RedditIngester
from tik_core.aggregator.task_supervision import supervise_task
from tik_core.aggregator.yahoo_ingester import YahooPoller

# =============================================================================
# Fixtures et helpers
# =============================================================================


class BoomRedis:
    """Mock Redis dont TOUTE écriture lève ConnectionError (panne simulée)."""

    def __init__(self) -> None:
        self.write_attempts = 0

    def _boom(self) -> None:
        self.write_attempts += 1
        raise redis.exceptions.ConnectionError("Connection refused (panne simulée)")

    async def setex(self, *args, **kwargs) -> None:  # noqa: ARG002
        self._boom()

    async def publish(self, *args, **kwargs) -> None:  # noqa: ARG002
        self._boom()

    async def set(self, *args, **kwargs) -> None:  # noqa: ARG002
        self._boom()

    async def get(self, *args, **kwargs) -> None:  # noqa: ARG002
        return None


class FakeClassifier(NewsClassifier):
    """Classifier factice minimal (jamais appelé : les fetch sont mockés)."""

    method_name = "fake"

    async def classify(self, title):  # type: ignore[override]  # noqa: ARG002
        return (0, 0)

    def reset_batch(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


@pytest.fixture
def instant_sleep(monkeypatch):
    """Neutralise asyncio.sleep : les intervalles réels vont de 60 s à 24 h."""

    async def _sleep(_seconds) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _sleep)


def _stop_after(ing, n_fetches: int):
    """Compteur d'appels fetch qui coupe la boucle après `n_fetches` cycles."""
    calls = {"n": 0}

    def _tick() -> None:
        calls["n"] += 1
        if calls["n"] >= n_fetches:
            ing._running = False

    return calls, _tick


ANOMALY_OK = {"type": "none", "severity": "ok", "score": 0.0, "detail": ""}


# =============================================================================
# Constat 1 — la boucle _run survit à une panne Redis et retente au cycle suivant
# =============================================================================


@pytest.mark.usefixtures("instant_sleep")
async def test_yahoo_run_survives_redis_connection_error():
    boom = BoomRedis()
    ing = YahooPoller(redis=boom, interval_s=60)
    calls, tick = _stop_after(ing, 2)

    async def fake_fetch(_client):
        tick()
        return MarketTick(
            entity_id="GOLD",
            source="yahoo",
            price=2400.0,
            volume=None,
            timestamp=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
            extra={},
        )

    ing._fetch_quote = fake_fetch
    ing._running = True
    await ing._run()  # ne doit PAS lever malgré la panne Redis

    assert calls["n"] == 2  # la boucle a survécu au 1er échec et retenté
    assert boom.write_attempts >= 2


@pytest.mark.usefixtures("instant_sleep")
async def test_fred_run_survives_redis_connection_error():
    boom = BoomRedis()
    ing = FredIngester(redis=boom, api_key="k", series_ids=["DGS10"], interval_s=3600)
    calls, tick = _stop_after(ing, 2)

    async def fake_fetch(_client, series_id):
        tick()
        return MacroDataPoint(
            series_id=series_id,
            source="fred",
            value=4.2,
            timestamp=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
        )

    ing._fetch_series = fake_fetch
    ing._running = True
    await ing._run()

    assert calls["n"] == 2
    assert boom.write_attempts >= 2


@pytest.mark.usefixtures("instant_sleep")
async def test_fear_greed_run_survives_redis_connection_error():
    boom = BoomRedis()
    ing = FearGreedIngester(redis=boom, interval_s=3600)
    calls, tick = _stop_after(ing, 2)

    async def fake_fetch(_client):
        tick()
        return {
            "source": "alternative_me_fng",
            "value": 20,
            "classification": "Extreme Fear",
            "timestamp": "2026-07-02T12:00:00+00:00",
            "fetched_at": "2026-07-02T12:00:00+00:00",
        }

    ing._fetch = fake_fetch
    ing._running = True
    await ing._run()

    assert calls["n"] == 2
    assert boom.write_attempts >= 2


@pytest.mark.usefixtures("instant_sleep")
async def test_cryptocompare_run_survives_redis_connection_error():
    boom = BoomRedis()
    ing = CryptoCompareIngester(
        redis=boom, api_key="k", classifier=FakeClassifier(), currency="BTC", interval_s=3600
    )
    calls, tick = _stop_after(ing, 2)

    async def fake_fetch(_client):
        tick()
        return {
            "source": "cryptocompare_news",
            "method": "fake",
            "currency": "BTC",
            "score": 0.1,
            "n_articles": 10,
            "n_bullish": 4,
            "n_bearish": 3,
            "n_neutral": 3,
            "n_distinct_publishers": 5,
            "headlines": [],
            "anomaly": ANOMALY_OK,
            "fetched_at": "2026-07-02T12:00:00+00:00",
        }

    ing._fetch = fake_fetch
    ing._running = True
    await ing._run()

    assert calls["n"] == 2
    assert boom.write_attempts >= 2


@pytest.mark.usefixtures("instant_sleep")
async def test_google_news_run_survives_redis_connection_error():
    boom = BoomRedis()
    ing = GoogleNewsIngester(
        redis=boom,
        classifier=FakeClassifier(),
        entity_id="BTC",
        query="Bitcoin",
        interval_s=1800,
    )
    calls, tick = _stop_after(ing, 2)

    async def fake_fetch(_client):
        tick()
        return {
            "source": "google_news_rss",
            "method": "fake",
            "entity_id": "BTC",
            "query": "Bitcoin",
            "score": 0.0,
            "n_articles": 10,
            "n_bullish": 3,
            "n_bearish": 3,
            "n_neutral": 4,
            "top_publishers": [],
            "headlines": [],
            "anomaly": ANOMALY_OK,
            "fetched_at": "2026-07-02T12:00:00+00:00",
        }

    ing._fetch = fake_fetch
    ing._running = True
    await ing._run()

    assert calls["n"] == 2
    assert boom.write_attempts >= 2


@pytest.mark.usefixtures("instant_sleep")
async def test_reddit_run_survives_redis_connection_error():
    boom = BoomRedis()
    ing = RedditIngester(
        redis=boom,
        classifier=FakeClassifier(),
        entity_id="BTC",
        subreddits=["Bitcoin"],
        interval_s=1800,
    )
    calls, tick = _stop_after(ing, 2)

    async def fake_fetch(_client):
        tick()
        return {
            "source": "reddit_btc",
            "method": "fake",
            "entity_id": "BTC",
            "subreddits": ["Bitcoin"],
            "score": 0.0,
            "n_articles": 5,
            "n_bullish": 2,
            "n_bearish": 2,
            "n_neutral": 1,
            "top_subreddits": [],
            "headlines": [],
            "anomaly": ANOMALY_OK,
            "fetched_at": "2026-07-02T12:00:00+00:00",
        }

    ing._fetch = fake_fetch
    ing._running = True
    await ing._run()

    assert calls["n"] == 2
    assert boom.write_attempts >= 2


@pytest.mark.usefixtures("instant_sleep")
async def test_gdelt_run_survives_redis_connection_error():
    boom = BoomRedis()
    ing = GdeltIngester(redis=boom, entity_id="GOLD", query='"gold price"', interval_s=7200)
    calls, tick = _stop_after(ing, 2)

    async def fake_fetch(_client):
        tick()
        return {
            "source": "gdelt_news",
            "method": "gdelt_tone_v2",
            "entity_id": "GOLD",
            "query": '"gold price"',
            "lang": "eng",
            "timespan": "1d",
            "tone": -1.2,
            "n_points": 24,
            "fetched_at": "2026-07-02T12:00:00+00:00",
        }

    ing._fetch = fake_fetch
    ing._running = True
    await ing._run()

    assert calls["n"] == 2
    assert boom.write_attempts >= 2


@pytest.mark.usefixtures("instant_sleep")
async def test_cftc_cot_run_survives_redis_connection_error():
    boom = BoomRedis()
    ing = CftcCotIngester(redis=boom, interval_s=24 * 3600)
    calls, tick = _stop_after(ing, 2)

    async def fake_fetch(_client):
        tick()
        return {
            "source": "cftc_cot",
            "commodity": "gold",
            "report_date": "2026-06-30",
            "mm_long": 100,
            "mm_short": 50,
            "mm_net_pct": 0.3333,
            "change_mm_long": 0,
            "change_mm_short": 0,
            "fetched_at": "2026-07-02T12:00:00+00:00",
        }

    ing._fetch = fake_fetch
    ing._running = True
    await ing._run()

    assert calls["n"] == 2
    assert boom.write_attempts >= 2


# =============================================================================
# Constat 4 — tik.macro.last.* écrit en SETEX (TTL 25h), plus jamais en SET nu
# =============================================================================


@pytest.mark.usefixtures("instant_sleep")
async def test_fred_macro_last_written_with_ttl():
    """La clé `tik.macro.last.{series}` doit expirer d'elle-même si FRED meurt."""
    recorded: list[tuple[str, int]] = []

    class RecordingRedis:
        async def publish(self, *args, **kwargs) -> None:  # noqa: ARG002
            return None

        async def setex(self, key, ttl, _value) -> None:
            recorded.append((key, ttl))

    ing = FredIngester(redis=RecordingRedis(), api_key="k", series_ids=["DGS10"])
    _calls, tick = _stop_after(ing, 1)

    async def fake_fetch(_client, series_id):
        tick()
        return MacroDataPoint(
            series_id=series_id,
            source="fred",
            value=4.2,
            timestamp=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
        )

    ing._fetch_series = fake_fetch
    ing._running = True
    await ing._run()

    assert recorded == [("tik.macro.last.DGS10", MACRO_LAST_TTL_S)]
    assert MACRO_LAST_TTL_S == 25 * 3600


# =============================================================================
# Constat 2 — supervision des tasks (done-callback ingester.task_died)
# =============================================================================


async def test_supervise_task_logs_task_died_on_exception():
    async def boom() -> None:
        raise ValueError("boom")

    with capture_logs() as logs:
        task = supervise_task(asyncio.create_task(boom()), "yahoo_poller")
        with pytest.raises(ValueError):
            await task
        await asyncio.sleep(0)  # laisse le done-callback s'exécuter

    died = [entry for entry in logs if entry.get("event") == "ingester.task_died"]
    assert len(died) == 1
    assert died[0]["ingester"] == "yahoo_poller"
    assert "boom" in died[0]["error"]


async def test_supervise_task_silent_on_cancellation():
    async def forever() -> None:
        await asyncio.sleep(3600)

    with capture_logs() as logs:
        task = supervise_task(asyncio.create_task(forever()), "yahoo_poller")
        await asyncio.sleep(0)  # laisse la task démarrer
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)

    assert not any(entry.get("event") == "ingester.task_died" for entry in logs)


async def test_start_attaches_supervision_to_run_task(monkeypatch):
    """start() doit brancher le done-callback : une boucle qui meurt = loggée."""
    ing = YahooPoller(redis=MagicMock())

    async def boom_run() -> None:
        raise RuntimeError("boucle morte")

    monkeypatch.setattr(ing, "_run", boom_run)
    with capture_logs() as logs:
        await ing.start()
        with pytest.raises(RuntimeError):
            await ing._task
        await asyncio.sleep(0)

    assert any(entry.get("event") == "ingester.task_died" for entry in logs)


# =============================================================================
# Constat 3 — stop() n'explose pas sur une task déjà morte
# =============================================================================


async def test_yahoo_stop_swallows_dead_task_exception():
    ing = YahooPoller(redis=MagicMock())

    async def boom() -> None:
        raise RuntimeError("déjà morte")

    ing._task = asyncio.create_task(boom())
    await asyncio.sleep(0)  # laisse la task mourir
    await ing.stop()  # ne doit pas lever


async def test_reddit_stop_swallows_dead_task_and_still_closes_classifier():
    closed = {"done": False}

    class ClosableClassifier(FakeClassifier):
        async def aclose(self) -> None:
            closed["done"] = True

    ing = RedditIngester(
        redis=MagicMock(),
        classifier=ClosableClassifier(),
        entity_id="BTC",
        subreddits=["Bitcoin"],
    )

    async def boom() -> None:
        raise RuntimeError("déjà morte")

    ing._task = asyncio.create_task(boom())
    await asyncio.sleep(0)
    await ing.stop()  # ne doit pas lever
    assert closed["done"] is True  # le cleanup aval a bien eu lieu


def test_run_ingesters_finally_protects_each_stop():
    """Garde-fou code source : chaque `await ing.stop()` du finally de
    run_ingesters est protégé individuellement (un stop() fautif ne doit pas
    interrompre l'arrêt des ingesters suivants ni la fermeture redis/engine)."""
    from tik_core.scripts import run_ingesters

    src = Path(run_ingesters.__file__).read_text(encoding="utf-8")
    assert "ingesters.stop_error" in src, "protection du stop() manquante dans le finally"
