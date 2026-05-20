"""Tests unitaires du CryptoCompare ingester (couche 6 — sentiment news).

Couvre :
- `_verdict_to_sentiment` (label trinaire bull/bear/neutral)
- `_extract_publisher` (3 stratégies : source_info.name, source brut, fallback)
- `_parse_unix_iso` (UNIX timestamp → ISO 8601 aware UTC)
- Champ `headlines` (Phase 1 trading manuel J+10)

Ce fichier de test couvre le ingester CryptoCompare. La logique
classifier (keywords vs Ollama) est testée séparément dans
`test_news_classifier.py`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tik_core.aggregator.cryptocompare_ingester import (
    MAX_HEADLINES,
    CryptoCompareIngester,
)
from tik_core.aggregator.news_classifier import NewsClassifier

# =============================================================================
# Helpers
# =============================================================================


class FakeClassifier(NewsClassifier):
    method_name = "fake"

    def __init__(self, verdicts: list[tuple[int, int]] | None = None) -> None:
        self.verdicts = list(verdicts) if verdicts else []
        self.calls: list[str] = []
        self.reset_calls = 0

    async def classify(self, title):  # type: ignore[override]
        self.calls.append(title or "")
        if not self.verdicts:
            return (0, 0)
        return self.verdicts.pop(0)

    def reset_batch(self) -> None:
        self.reset_calls += 1

    async def aclose(self) -> None:
        pass


class _FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200) -> None:
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._json


class _FakeClient:
    def __init__(self, json_data: dict) -> None:
        self._json = json_data

    async def get(self, url, **kwargs):
        return _FakeResponse(self._json)


def _make_ingester(
    classifier: NewsClassifier | None = None,
) -> CryptoCompareIngester:
    # AsyncMock requis depuis P6 (Paquet 21) car _fetch lit/écrit la baseline
    # volume via await self.redis.get/setex pour la détection volume_spike.
    redis_mock = MagicMock()
    redis_mock.get = AsyncMock(return_value=None)  # baseline absente → ok
    redis_mock.setex = AsyncMock(return_value=True)
    return CryptoCompareIngester(
        redis=redis_mock,
        api_key="fake-key",
        classifier=classifier or FakeClassifier(),
        currency="BTC",
        interval_s=3600,
    )


def _make_article(
    title: str,
    published_on: int = 1714521600,
    url: str = "https://coindesk.com/article",
    publisher_info_name: str | None = "CoinDesk",
    source_raw: str = "coindesk",
) -> dict:
    article = {
        "title": title,
        "url": url,
        "published_on": published_on,
        "source": source_raw,
    }
    if publisher_info_name is not None:
        article["source_info"] = {"name": publisher_info_name}
    return article


# =============================================================================
# _verdict_to_sentiment
# =============================================================================


@pytest.mark.parametrize(
    "n_bull, n_bear, expected",
    [
        (1, 0, "bull"),
        (0, 1, "bear"),
        (0, 0, "neutral"),
        (1, 1, "neutral"),
        (2, 1, "bull"),
        (1, 2, "bear"),
    ],
)
def test_verdict_to_sentiment(n_bull, n_bear, expected):
    assert CryptoCompareIngester._verdict_to_sentiment(n_bull, n_bear) == expected


# =============================================================================
# _extract_publisher
# =============================================================================


def test_extract_publisher_from_source_info_name():
    article = _make_article("T", publisher_info_name="CoinDesk", source_raw="coindesk")
    assert CryptoCompareIngester._extract_publisher(article) == "CoinDesk"


def test_extract_publisher_fallback_to_source_raw():
    """Si source_info.name est absent, on prend source brut."""
    article = {"source": "decrypt"}
    assert CryptoCompareIngester._extract_publisher(article) == "decrypt"


def test_extract_publisher_returns_unknown_when_no_clue():
    article = {}
    assert CryptoCompareIngester._extract_publisher(article) == "unknown"


# =============================================================================
# _parse_unix_iso
# =============================================================================


def test_parse_unix_iso_int():
    """Un int UNIX timestamp est converti en ISO aware UTC."""
    iso = CryptoCompareIngester._parse_unix_iso(1714521600)
    assert iso is not None
    assert iso.startswith("2024-")
    assert "+00:00" in iso or iso.endswith("Z") or "+" in iso


def test_parse_unix_iso_str():
    iso = CryptoCompareIngester._parse_unix_iso("1714521600")
    assert iso is not None
    assert iso.startswith("2024-")


def test_parse_unix_iso_invalid_returns_none():
    assert CryptoCompareIngester._parse_unix_iso(None) is None
    assert CryptoCompareIngester._parse_unix_iso("") is None
    assert CryptoCompareIngester._parse_unix_iso("not-a-number") is None


# =============================================================================
# Champ `headlines` (Phase 1 trading manuel J+10)
# =============================================================================


async def test_fetch_includes_headlines_field():
    classifier = FakeClassifier(verdicts=[(1, 0), (0, 1), (0, 0)])
    ing = _make_ingester(classifier=classifier)
    payload_data = {
        "Type": 100,
        "Data": [
            _make_article("BTC ATH"),
            _make_article("BTC dump"),
            _make_article("BTC sideways"),
        ],
    }
    client = _FakeClient(payload_data)

    payload = await ing._fetch(client)
    assert payload is not None
    assert "headlines" in payload
    assert isinstance(payload["headlines"], list)
    assert len(payload["headlines"]) == 3


async def test_fetch_headlines_format_and_sentiment():
    classifier = FakeClassifier(verdicts=[(1, 0), (0, 1)])
    ing = _make_ingester(classifier=classifier)
    payload_data = {
        "Type": 100,
        "Data": [
            _make_article("BTC ATH"),
            _make_article("BTC dump"),
        ],
    }
    client = _FakeClient(payload_data)

    payload = await ing._fetch(client)
    assert payload is not None
    h_bull, h_bear = payload["headlines"]
    assert h_bull["title"] == "BTC ATH"
    assert h_bull["sentiment"] == "bull"
    assert h_bull["publisher"] == "CoinDesk"
    assert h_bull["url"] == "https://coindesk.com/article"
    assert h_bear["sentiment"] == "bear"


async def test_fetch_headlines_capped_at_max():
    """Si l'API CryptoCompare renvoie plus de MAX_HEADLINES articles, on cap."""
    classifier = FakeClassifier(verdicts=[(0, 0)] * 100)
    ing = _make_ingester(classifier=classifier)
    payload_data = {
        "Type": 100,
        "Data": [_make_article(f"Article {i}") for i in range(100)],
    }
    client = _FakeClient(payload_data)

    payload = await ing._fetch(client)
    assert payload is not None
    assert payload["n_articles"] == 100  # tous classifiés
    assert len(payload["headlines"]) == MAX_HEADLINES  # cappé à 25


async def test_fetch_returns_none_when_api_type_not_100():
    """Si l'API CryptoCompare retourne Type != 100, on log un warning et None."""
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient({"Type": 99, "Message": "rate limited"})

    payload = await ing._fetch(client)
    assert payload is None
