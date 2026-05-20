"""Tests unitaires du Google News ingester (couche 6 — sentiment news).

Couvre :
- `_extract_publisher` (3 stratégies : balise <source>, suffix " - X", fallback "unknown")
- `_build_url` (encoding URL des queries avec espaces, guillemets, opérateurs)
- `_fetch` complet : parsing RSS, classification batch, score net, top_publishers
- Cas limites : RSS vide, HTTP error, RSS malformé
- Garanties opérationnelles ADR-008 : `reset_batch()` appelé en début de cycle,
  un classifier distinct par instance.

Pas de Redis ni de DB : on teste `_fetch` directement, pas la boucle `_run`.
La validation runtime de `_run` (Redis setex + publish + sleep) se fait après
rebuild Docker via vérification des clés `tik.sentiment.google_news.{btc,gold}`.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from tik_core.aggregator.google_news_ingester import (
    GOOGLE_NEWS_RSS_TPL,
    REDIS_KEY_TPL,
    GoogleNewsIngester,
)
from tik_core.aggregator.news_classifier import NewsClassifier

# =============================================================================
# Fixtures et helpers
# =============================================================================

RSS_FIXTURE_BTC = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Bitcoin - Google News</title>
  <link>https://news.google.com/rss/search?q=Bitcoin</link>
  <description>Google News</description>
  <item>
    <title>Bitcoin surges to record high - Reuters</title>
    <link>https://news.google.com/rss/articles/abc</link>
    <pubDate>Wed, 30 Apr 2026 14:00:00 GMT</pubDate>
    <description>Article 1</description>
    <source url="https://reuters.com">Reuters</source>
  </item>
  <item>
    <title>Crypto crash erases gains - Bloomberg</title>
    <link>https://news.google.com/rss/articles/def</link>
    <pubDate>Wed, 30 Apr 2026 13:00:00 GMT</pubDate>
    <description>Article 2</description>
    <source url="https://bloomberg.com">Bloomberg</source>
  </item>
  <item>
    <title>BTC market analysis without source tag</title>
    <link>https://news.google.com/rss/articles/ghi</link>
    <pubDate>Wed, 30 Apr 2026 12:00:00 GMT</pubDate>
    <description>Article 3</description>
  </item>
</channel>
</rss>"""

RSS_FIXTURE_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Empty - Google News</title>
  <link>https://news.google.com/rss/search?q=nothing</link>
  <description>No items</description>
</channel>
</rss>"""


class FakeClassifier(NewsClassifier):
    """Classifier de test contrôlé pour observer les appels et fixer les verdicts."""

    method_name = "fake"

    def __init__(self, verdicts: list[tuple[int, int]] | None = None) -> None:
        self.verdicts = list(verdicts) if verdicts else []
        self.calls: list[str] = []
        self.reset_calls = 0
        self.aclose_called = False

    async def classify(self, title):  # type: ignore[override]
        self.calls.append(title or "")
        if not self.verdicts:
            return (0, 0)
        return self.verdicts.pop(0)

    def reset_batch(self) -> None:
        self.reset_calls += 1

    async def aclose(self) -> None:
        self.aclose_called = True


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            # Le ingester catch `Exception` au sens large — peu importe le type
            # exact pour tester la gestion gracieuse des erreurs HTTP.
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """Mock minimal d'`httpx.AsyncClient` qui retourne `text` ou `raise_exc`."""

    def __init__(
        self,
        response_text: str = "",
        status_code: int = 200,
        raise_exc: Exception | None = None,
    ) -> None:
        self._text = response_text
        self._status = status_code
        self._raise_exc = raise_exc
        self.last_url: str | None = None
        self.last_kwargs: dict | None = None

    async def get(self, url: str, **kwargs):
        self.last_url = url
        self.last_kwargs = kwargs
        if self._raise_exc:
            raise self._raise_exc
        return _FakeResponse(self._text, self._status)


def _make_ingester(
    classifier: NewsClassifier | None = None,
    entity_id: str = "BTC",
    query: str = "Bitcoin",
    limit: int = 50,
) -> GoogleNewsIngester:
    redis_mock = MagicMock()
    return GoogleNewsIngester(
        redis=redis_mock,
        classifier=classifier or FakeClassifier(),
        entity_id=entity_id,
        query=query,
        interval_s=1800,
        limit=limit,
    )


# =============================================================================
# _extract_publisher — strategies
# =============================================================================


def test_extract_publisher_from_source_tag():
    """Quand entry.source.title est présent, on le prend en priorité (canonique)."""
    entry = MagicMock()
    entry.source.title = "Reuters"
    assert GoogleNewsIngester._extract_publisher(entry) == "Reuters"


def test_extract_publisher_from_title_suffix_when_no_source():
    """Sans balise <source>, on prend le suffixe ' - X' du title.

    `spec=["get"]` limite les attributs accessibles → `entry.source` lève
    AttributeError, ce que le helper attrape pour passer au fallback.
    """
    entry = MagicMock(spec=["get"])
    entry.get.return_value = "Bitcoin surges - CoinDesk"
    assert GoogleNewsIngester._extract_publisher(entry) == "CoinDesk"


def test_extract_publisher_returns_unknown_when_no_clue():
    """Aucune source et aucun suffixe → 'unknown'."""
    entry = MagicMock(spec=["get"])
    entry.get.return_value = "Bitcoin surges to ATH"  # pas de " - "
    assert GoogleNewsIngester._extract_publisher(entry) == "unknown"


def test_extract_publisher_handles_multiple_dashes_in_title():
    """'Title - subtitle - Publisher' → on prend le dernier segment."""
    entry = MagicMock(spec=["get"])
    entry.get.return_value = "BTC update - daily - Financial Times"
    assert GoogleNewsIngester._extract_publisher(entry) == "Financial Times"


def test_extract_publisher_strips_whitespace():
    entry = MagicMock()
    entry.source.title = "  Bloomberg  "
    assert GoogleNewsIngester._extract_publisher(entry) == "Bloomberg"


def test_extract_publisher_from_real_feedparser_entries():
    """Validation bout-en-bout : le RSS fixture est parsé par feedparser
    et on vérifie l'extraction publisher sur des entries réelles."""
    import feedparser

    feed = feedparser.parse(RSS_FIXTURE_BTC)
    # 2 premières entries : balise <source> → publisher canonique
    assert GoogleNewsIngester._extract_publisher(feed.entries[0]) == "Reuters"
    assert GoogleNewsIngester._extract_publisher(feed.entries[1]) == "Bloomberg"
    # 3e entry : pas de <source> et pas de " - " dans le titre → "unknown"
    assert GoogleNewsIngester._extract_publisher(feed.entries[2]) == "unknown"


# =============================================================================
# _build_url — encoding des queries
# =============================================================================


def test_build_url_simple_query():
    ing = _make_ingester(query="Bitcoin")
    url = ing._build_url()
    assert url == GOOGLE_NEWS_RSS_TPL.format(query="Bitcoin")
    assert url.startswith("https://news.google.com/rss/search?q=Bitcoin&")


def test_build_url_quoted_query_for_gold():
    """`"gold price"` doit être encodé (%22) pour préserver les guillemets."""
    ing = _make_ingester(query='"gold price"', entity_id="GOLD")
    url = ing._build_url()
    assert "%22gold+price%22" in url


def test_build_url_with_special_chars():
    """OR opérateur Google avec espace → URL-encodé en `+`."""
    ing = _make_ingester(query="Bitcoin OR Ethereum")
    url = ing._build_url()
    assert "Bitcoin+OR+Ethereum" in url


# =============================================================================
# _fetch — chaîne complète : RSS → classify → score
# =============================================================================


async def test_fetch_with_valid_rss_full_pipeline():
    """3 entrées RSS, classifier qui dit BULL/BEAR/NEUTRAL → score = 0."""
    classifier = FakeClassifier(verdicts=[(1, 0), (0, 1), (0, 0)])
    ing = _make_ingester(classifier=classifier, entity_id="BTC")
    client = _FakeClient(response_text=RSS_FIXTURE_BTC)

    payload = await ing._fetch(client)

    assert payload is not None
    assert payload["source"] == "google_news_rss"
    assert payload["method"] == "fake"
    assert payload["entity_id"] == "BTC"
    assert payload["query"] == "Bitcoin"
    assert payload["n_articles"] == 3
    assert payload["n_bullish"] == 1
    assert payload["n_bearish"] == 1
    assert payload["n_neutral"] == 1
    # score net = (1 - 1) / (1 + 1) = 0
    assert payload["score"] == 0.0
    assert "fetched_at" in payload


async def test_fetch_score_strong_bullish():
    classifier = FakeClassifier(verdicts=[(1, 0), (1, 0), (0, 0)])
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(response_text=RSS_FIXTURE_BTC)

    payload = await ing._fetch(client)
    assert payload is not None
    # 2 bull, 0 bear, 1 neutral → score = (2-0)/(2+0) = 1.0
    assert payload["score"] == 1.0
    assert payload["n_bullish"] == 2
    assert payload["n_neutral"] == 1


async def test_fetch_score_zero_when_no_classified():
    """Tous les titres sont neutres → score = 0 (et pas une division par zéro)."""
    classifier = FakeClassifier(verdicts=[(0, 0), (0, 0), (0, 0)])
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(response_text=RSS_FIXTURE_BTC)

    payload = await ing._fetch(client)
    assert payload is not None
    assert payload["score"] == 0.0
    assert payload["n_neutral"] == 3


async def test_fetch_top_publishers_extracted_and_sorted():
    """Les top_publishers sont extraits via _extract_publisher et triés par count."""
    classifier = FakeClassifier(verdicts=[(0, 0)] * 3)
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(response_text=RSS_FIXTURE_BTC)

    payload = await ing._fetch(client)
    assert payload is not None
    pubs = payload["top_publishers"]
    # 3 entries → 3 publishers : Reuters, Bloomberg, et 1 fallback via " - X"
    # ou "unknown" pour la 3e entry sans " - " ni <source>
    assert len(pubs) == 3
    names = {p["name"] for p in pubs}
    assert "Reuters" in names
    assert "Bloomberg" in names
    # Tous comptent 1 fois
    assert all(p["count"] == 1 for p in pubs)


async def test_fetch_calls_classifier_for_each_title():
    classifier = FakeClassifier(verdicts=[(0, 0)] * 3)
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(response_text=RSS_FIXTURE_BTC)

    await ing._fetch(client)

    assert len(classifier.calls) == 3
    # Le classifier reçoit les titres NETTOYÉS du suffix " - Publisher"
    # (cf. _strip_publisher_suffix, ajouté Phase 1 J+10 pour la dédup
    # multi-source côté endpoint /headlines).
    assert "Bitcoin surges to record high" in classifier.calls
    assert "Crypto crash erases gains" in classifier.calls
    assert "BTC market analysis without source tag" in classifier.calls


async def test_fetch_resets_classifier_circuit_breaker():
    """ADR-006 : reset_batch() est appelé en début de cycle (réarme Ollama)."""
    classifier = FakeClassifier(verdicts=[(0, 0)] * 3)
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(response_text=RSS_FIXTURE_BTC)

    await ing._fetch(client)
    assert classifier.reset_calls == 1

    # Un second cycle → second reset
    classifier.verdicts = [(0, 0)] * 3
    await ing._fetch(client)
    assert classifier.reset_calls == 2


async def test_fetch_respects_limit():
    """Si le RSS retourne plus d'entrées que `limit`, on tronque."""
    classifier = FakeClassifier(verdicts=[(0, 0)] * 100)
    ing = _make_ingester(classifier=classifier, limit=2)
    client = _FakeClient(response_text=RSS_FIXTURE_BTC)

    payload = await ing._fetch(client)
    assert payload is not None
    assert payload["n_articles"] == 2  # tronqué à 2 sur les 3 du fixture
    assert len(classifier.calls) == 2


async def test_fetch_with_empty_rss_returns_none():
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(response_text=RSS_FIXTURE_EMPTY)

    payload = await ing._fetch(client)
    assert payload is None
    # Le classifier ne doit pas avoir été appelé
    assert classifier.calls == []
    assert classifier.reset_calls == 0


async def test_fetch_with_http_error_returns_none():
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(raise_exc=httpx.ConnectError("network unreachable"))

    payload = await ing._fetch(client)
    assert payload is None
    assert classifier.calls == []


async def test_fetch_with_4xx_status_returns_none():
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(response_text="", status_code=429)

    payload = await ing._fetch(client)
    assert payload is None


async def test_fetch_with_malformed_xml_returns_none_or_handles_gracefully():
    """feedparser est tolérant — un XML cassé donne 0 entries → None."""
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(response_text="<not-an-rss>broken")

    payload = await ing._fetch(client)
    assert payload is None


async def test_fetch_url_uses_correct_query():
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier, query='"gold price"', entity_id="GOLD")
    client = _FakeClient(response_text=RSS_FIXTURE_EMPTY)

    await ing._fetch(client)
    assert client.last_url is not None
    assert "%22gold+price%22" in client.last_url


async def test_fetch_url_includes_user_agent():
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(response_text=RSS_FIXTURE_EMPTY)

    await ing._fetch(client)
    headers = client.last_kwargs.get("headers", {}) if client.last_kwargs else {}
    assert "User-Agent" in headers


# =============================================================================
# Constantes et nommage
# =============================================================================


def test_redis_key_template_contains_entity_placeholder():
    assert "{entity}" in REDIS_KEY_TPL
    assert REDIS_KEY_TPL.format(entity="btc") == "tik.sentiment.google_news.btc"
    assert REDIS_KEY_TPL.format(entity="gold") == "tik.sentiment.google_news.gold"


def test_ingester_name_and_layer():
    ing = _make_ingester()
    assert ing.name == "google_news_ingester"
    assert ing.layer == 6  # couche sentiment textuel


# =============================================================================
# Lifecycle (start/stop)
# =============================================================================


async def test_stop_calls_classifier_aclose():
    """ADR-006 : le ingester doit fermer son classifier proprement."""
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    # On ne lance pas start() (qui boucle), on appelle juste stop() pour vérifier aclose
    await ing.stop()
    assert classifier.aclose_called is True


# =============================================================================
# Champ `headlines` (Phase 1 trading manuel J+10)
# =============================================================================


async def test_fetch_includes_headlines_field():
    """Le payload inclut une liste `headlines` avec les titres bruts classifiés."""
    classifier = FakeClassifier(verdicts=[(1, 0), (0, 1), (0, 0)])
    ing = _make_ingester(classifier=classifier, entity_id="BTC")
    client = _FakeClient(response_text=RSS_FIXTURE_BTC)

    payload = await ing._fetch(client)
    assert payload is not None
    assert "headlines" in payload
    assert isinstance(payload["headlines"], list)
    assert len(payload["headlines"]) == 3


async def test_fetch_headlines_have_complete_format():
    """Chaque headline a title/url/publisher/sentiment/fetched_at + published_at optionnel."""
    classifier = FakeClassifier(verdicts=[(1, 0), (0, 1), (0, 0)])
    ing = _make_ingester(classifier=classifier, entity_id="BTC")
    client = _FakeClient(response_text=RSS_FIXTURE_BTC)

    payload = await ing._fetch(client)
    assert payload is not None
    for h in payload["headlines"]:
        assert "title" in h and isinstance(h["title"], str)
        assert "url" in h  # peut être None ou string
        assert "publisher" in h and isinstance(h["publisher"], str)
        assert "sentiment" in h and h["sentiment"] in ("bull", "bear", "neutral")
        assert "fetched_at" in h and isinstance(h["fetched_at"], str)
        assert "published_at" in h  # peut être None ou ISO string


async def test_fetch_headlines_sentiment_matches_classifier_verdict():
    """Le label sentiment correspond strictement au verdict du classifier."""
    classifier = FakeClassifier(verdicts=[(1, 0), (0, 1), (0, 0)])
    ing = _make_ingester(classifier=classifier, entity_id="BTC")
    client = _FakeClient(response_text=RSS_FIXTURE_BTC)

    payload = await ing._fetch(client)
    assert payload is not None
    sentiments = [h["sentiment"] for h in payload["headlines"]]
    assert sentiments == ["bull", "bear", "neutral"]


def test_strip_publisher_suffix_removes_trailing_publisher():
    """Le titre est nettoyé du suffix ' - Publisher' (préserve la dédup multi-source)."""
    out = GoogleNewsIngester._strip_publisher_suffix(
        "Bitcoin surges to record high - Reuters",
        "Reuters",
    )
    assert out == "Bitcoin surges to record high"


def test_strip_publisher_suffix_no_match_returns_unchanged():
    """Si le titre ne se termine pas par ' - Publisher', il est renvoyé inchangé."""
    out = GoogleNewsIngester._strip_publisher_suffix(
        "Bitcoin surges to record high",
        "Reuters",
    )
    assert out == "Bitcoin surges to record high"


def test_strip_publisher_suffix_unknown_publisher_returns_unchanged():
    """Si publisher='unknown', on ne touche pas au titre."""
    out = GoogleNewsIngester._strip_publisher_suffix(
        "Bitcoin update - Some site",
        "unknown",
    )
    assert out == "Bitcoin update - Some site"


async def test_fetch_headlines_strip_publisher_suffix_in_titles():
    """Les titres dans le champ headlines sont nettoyés du ' - Publisher' final."""
    classifier = FakeClassifier(verdicts=[(1, 0), (0, 1), (0, 0)])
    ing = _make_ingester(classifier=classifier, entity_id="BTC")
    client = _FakeClient(response_text=RSS_FIXTURE_BTC)

    payload = await ing._fetch(client)
    assert payload is not None
    titles = [h["title"] for h in payload["headlines"]]
    # Les 2 premiers fixtures ont " - Reuters" / " - Bloomberg" → doivent être nettoyés
    assert "Bitcoin surges to record high" in titles
    assert "Crypto crash erases gains" in titles
    # Le 3e fixture n'a pas de suffix → reste tel quel
    assert "BTC market analysis without source tag" in titles


async def test_fetch_headlines_capped_at_max_25():
    """Si plus de 25 entries sont classifiées, le champ headlines est cappé à 25.

    Le score net continue d'être calculé sur TOUS les titres classifiés
    (rétrocompat — calcul inchangé).
    """
    # 50 entries identiques, classifier neutre
    rss_50 = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>"""
    for i in range(50):
        rss_50 += (
            f"<item><title>BTC update {i} - Reuters</title>"
            f"<link>https://news.google.com/{i}</link>"
            f"<pubDate>Wed, 30 Apr 2026 14:00:00 GMT</pubDate>"
            f"<source url='https://reuters.com'>Reuters</source>"
            f"</item>"
        )
    rss_50 += "</channel></rss>"

    classifier = FakeClassifier(verdicts=[(0, 0)] * 50)
    ing = _make_ingester(classifier=classifier, entity_id="BTC", limit=50)
    client = _FakeClient(response_text=rss_50)

    payload = await ing._fetch(client)
    assert payload is not None
    # n_articles compte tous les titres classifiés (pas cappé)
    assert payload["n_articles"] == 50
    # headlines liste cappée à 25
    assert len(payload["headlines"]) == 25
