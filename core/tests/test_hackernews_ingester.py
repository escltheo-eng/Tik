"""Tests HackerNewsIngester (ADR-039 — candidat remplaçant Reddit, SHADOW).

Mêmes patterns que test_reddit_ingester : httpx mocké via MockTransport,
FakeClassifier contrôlé, résilience Redis (audit 2026-07-02).
"""

from __future__ import annotations

import json
import math
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from tik_core.aggregator.hackernews_ingester import (
    HISTORY_MAX,
    REDIS_KEY_TPL,
    HackerNewsIngester,
)
from tik_core.aggregator.news_classifier import NewsClassifier


class FakeClassifier(NewsClassifier):
    method_name = "fake"

    def __init__(
        self,
        verdicts_by_title: dict[str, tuple[int, int]] | None = None,
        default: tuple[int, int] = (0, 0),
    ) -> None:
        self.verdicts_by_title = verdicts_by_title or {}
        self.default = default
        self.calls: list[str] = []
        self.reset_calls = 0

    async def classify(self, title):  # type: ignore[override]
        self.calls.append(title or "")
        return self.verdicts_by_title.get(title or "", self.default)

    def reset_batch(self) -> None:
        self.reset_calls += 1


def _hit(object_id: str, title: str, points: int = 50) -> dict:
    return {
        "objectID": object_id,
        "title": title,
        "points": points,
        "url": f"https://example.com/{object_id}",
        "created_at": "2026-07-02T10:00:00Z",
    }


def _client_returning(hits_by_query: dict[str, list[dict]]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("query", "")
        return httpx.Response(200, json={"hits": hits_by_query.get(query, [])})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _make_ingester(classifier: NewsClassifier | None = None) -> HackerNewsIngester:
    return HackerNewsIngester(
        redis=MagicMock(),
        classifier=classifier or FakeClassifier(),
        entity="BTC",
    )


# ----- _fetch : agrégation, dédup, score -----


@pytest.mark.asyncio
async def test_fetch_aggregates_and_weights_by_log_points():
    classifier = FakeClassifier(
        verdicts_by_title={
            "Bitcoin ETF inflows surge": (2, 0),  # bull
            "BTC crashes below support": (0, 2),  # bear
        }
    )
    ing = _make_ingester(classifier)
    client = _client_returning(
        {
            "bitcoin": [_hit("1", "Bitcoin ETF inflows surge", points=99)],
            "btc": [_hit("2", "BTC crashes below support", points=9)],
        }
    )
    point = await ing._fetch(client)
    assert point is not None
    assert point["source"] == "hackernews_btc"
    assert point["n_articles"] == 2
    assert point["n_bullish"] == 1
    assert point["n_bearish"] == 1
    # Score net = (log(100)*1 + log(10)*(-1)) / (log(100) + log(10))
    expected = (math.log(100) - math.log(10)) / (math.log(100) + math.log(10))
    assert point["score"] == pytest.approx(expected, abs=1e-4)
    # Le circuit breaker batch a été réarmé (ADR-006/008)
    assert classifier.reset_calls == 1


@pytest.mark.asyncio
async def test_fetch_dedupes_across_queries():
    """Les requêtes bitcoin/btc se recouvrent : un même objectID compte une fois."""
    ing = _make_ingester()
    shared = _hit("42", "Bitcoin hits new level")
    client = _client_returning({"bitcoin": [shared], "btc": [shared]})
    point = await ing._fetch(client)
    assert point is not None
    assert point["n_articles"] == 1


@pytest.mark.asyncio
async def test_fetch_returns_none_when_empty():
    ing = _make_ingester()
    client = _client_returning({})
    assert await ing._fetch(client) is None


@pytest.mark.asyncio
async def test_fetch_survives_http_error_and_malformed_payload():
    """Une requête en erreur / un payload difforme → best-effort, pas d'exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("query", "")
        if query == "bitcoin":
            return httpx.Response(500)
        return httpx.Response(200, json={"unexpected": "shape"})

    ing = _make_ingester()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await ing._fetch(client) is None


@pytest.mark.asyncio
async def test_fetch_skips_hits_without_title_or_id():
    ing = _make_ingester()
    client = _client_returning(
        {
            "bitcoin": [
                {"objectID": "1", "title": "", "points": 50},
                {"objectID": "", "title": "No id", "points": 50},
                "not-a-dict",
                _hit("2", "Valid story"),
            ]
        }
    )
    point = await ing._fetch(client)
    assert point is not None
    assert point["n_articles"] == 1


@pytest.mark.asyncio
async def test_headlines_have_expected_shape_and_fallback_url():
    ing = _make_ingester()
    no_url = _hit("7", "Story without url")
    no_url.pop("url")
    client = _client_returning({"bitcoin": [no_url]})
    point = await ing._fetch(client)
    h = point["headlines"][0]
    assert h["publisher"] == "hackernews"
    assert h["url"] == "https://news.ycombinator.com/item?id=7"
    assert h["sentiment"] in ("bullish", "bearish", "neutral")
    assert h["published_at"] == "2026-07-02T10:00:00Z"


# ----- _run : écritures Redis (setex + history cappé) et résilience -----


@pytest.mark.asyncio
async def test_run_writes_setex_history_and_survives_redis_error(monkeypatch):
    """1er cycle : Redis en panne → la boucle survit ; 2e cycle : écritures OK."""
    redis = MagicMock()
    calls = {"setex": 0}

    async def _setex(key, ttl, payload):
        calls["setex"] += 1
        if calls["setex"] == 1:
            raise ConnectionError("redis down")

    redis.setex = _setex
    redis.lpush = AsyncMock()
    redis.ltrim = AsyncMock()

    ing = HackerNewsIngester(redis=redis, classifier=FakeClassifier(), entity="BTC")
    cycles = {"n": 0}

    async def _fake_fetch(client):
        cycles["n"] += 1
        if cycles["n"] > 2:
            ing._running = False
        return {
            "source": "hackernews_btc",
            "method": "fake",
            "entity_id": "BTC",
            "queries": ["bitcoin"],
            "score": 0.5,
            "n_articles": 1,
            "n_bullish": 1,
            "n_bearish": 0,
            "n_neutral": 0,
            "headlines": [],
            "fetched_at": "2026-07-02T10:00:00Z",
        }

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(ing, "_fetch", _fake_fetch)
    monkeypatch.setattr("tik_core.aggregator.hackernews_ingester.asyncio.sleep", _no_sleep)
    ing._running = True
    await ing._run()  # ne doit PAS lever malgré la panne Redis du 1er cycle

    assert calls["setex"] >= 2  # la boucle a survécu et retenté
    # History : LPUSH + LTRIM cappé à HISTORY_MAX
    redis.lpush.assert_called()
    args, _ = redis.ltrim.call_args
    assert args[1] == 0 and args[2] == HISTORY_MAX - 1
    key = redis.lpush.call_args[0][0]
    assert key == REDIS_KEY_TPL.format(entity="btc") + ".history"
    payload = json.loads(redis.lpush.call_args[0][1])
    assert payload["source"] == "hackernews_btc"


def test_shadow_strict_no_engine_wiring():
    """Garde-fou : AUCUN _enrich_with_hackernews dans les moteurs (shadow strict).

    L'enrôlement d'une source sur le combined_bias exige une mesure ≥ 2 semaines
    (règle projet) ET une décision utilisatrice — ce test échoue si quelqu'un
    câble HN dans un moteur sans passer par là.
    """
    from pathlib import Path

    scoring_dir = Path(__file__).resolve().parents[1] / "src" / "tik_core" / "scoring"
    for f in scoring_dir.glob("*.py"):
        assert "hackernews" not in f.read_text(encoding="utf-8").lower(), (
            f"{f.name} référence hackernews — enrôlement interdit sans mesure shadow ≥ 2 sem"
        )
