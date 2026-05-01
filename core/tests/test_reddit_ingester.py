"""Tests unitaires du Reddit ingester (couche 6 — sentiment retail BTC).

Couvre :
- `_filter_post` (filtres stickied/NSFW/score<5)
- `_verdict_to_value` (mapping classifier → trinaire)
- `_fetch_sub` (un sub) : payload valide, erreur HTTP, payload malformé
- `_fetch` complet : multi-sub, agrégation, pondération log(score+1),
  top_subreddits, gestion sub partiellement disponible
- Cas limites : tous filtrés, classifier mocké pour vérdicts contrôlés

Pas de Redis ni de DB : on teste `_fetch` directement, pas la boucle `_run`.
La validation runtime de `_run` (Redis setex + publish) se fait après
rebuild Docker via vérification de la clé `tik.sentiment.reddit.btc`.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import httpx
import pytest

from tik_core.aggregator.news_classifier import NewsClassifier
from tik_core.aggregator.reddit_ingester import (
    REDIS_KEY_TPL,
    RedditIngester,
)


# =============================================================================
# Fixtures et helpers
# =============================================================================


def _make_post(
    title: str,
    score: int,
    subreddit: str = "Bitcoin",
    stickied: bool = False,
    over_18: bool = False,
    kind: str = "t3",
) -> dict:
    """Construit un objet `{"kind": "t3", "data": {...}}` à la sauce Reddit JSON."""
    return {
        "kind": kind,
        "data": {
            "title": title,
            "score": score,
            "subreddit": subreddit,
            "stickied": stickied,
            "over_18": over_18,
            "num_comments": 12,
            "created_utc": 1714521600.0,
        },
    }


def _make_listing(posts: list[dict]) -> dict:
    """Construit le payload Reddit JSON `/r/<sub>/hot.json`."""
    return {
        "kind": "Listing",
        "data": {
            "after": "t3_xxx",
            "before": None,
            "children": posts,
        },
    }


REDDIT_FIXTURE_BITCOIN = _make_listing(
    [
        # 1 post stickied (modo announcement) — doit être filtré
        _make_post("Daily discussion - read the rules", score=500, stickied=True),
        # 1 post bull bien upvoté
        _make_post("Bitcoin surges to ATH on ETF inflows", score=1500),
        # 1 post bear modéré
        _make_post("BTC dumps after Fed announcement", score=420),
        # 1 post avec score trop faible — doit être filtré
        _make_post("Why I'm hodling forever", score=2),
        # 1 post NSFW (rare mais filtre de propreté) — doit être filtré
        _make_post("[NSFW] something inappropriate", score=200, over_18=True),
        # 1 post neutre
        _make_post("Bitcoin price moves sideways", score=80),
    ]
)

REDDIT_FIXTURE_CRYPTOMARKETS = _make_listing(
    [
        # 1 post bull modéré
        _make_post(
            "BTC breaks resistance at 70k",
            score=300,
            subreddit="CryptoMarkets",
        ),
        # 1 post bear viral
        _make_post(
            "Capitulation incoming — chart analysis",
            score=2000,
            subreddit="CryptoMarkets",
        ),
    ]
)


class FakeClassifier(NewsClassifier):
    """Classifier de test contrôlé : verdicts fixés à l'avance par titre ou par index."""

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
        self.aclose_called = False

    async def classify(self, title):  # type: ignore[override]
        self.calls.append(title or "")
        return self.verdicts_by_title.get(title or "", self.default)

    def reset_batch(self) -> None:
        self.reset_calls += 1

    async def aclose(self) -> None:
        self.aclose_called = True


class _FakeResponse:
    def __init__(self, json_data: dict | None = None, status_code: int = 200) -> None:
        self._json = json_data or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._json


class _FakeClient:
    """Mock minimal d'`httpx.AsyncClient` qui retourne un payload par sub."""

    def __init__(
        self,
        responses_by_sub: dict[str, dict] | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self.responses_by_sub = responses_by_sub or {}
        self._raise_exc = raise_exc
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        if self._raise_exc:
            raise self._raise_exc
        # On extrait le sub depuis l'URL /r/<sub>/hot.json
        for sub, payload in self.responses_by_sub.items():
            if f"/r/{sub}/" in url:
                return _FakeResponse(payload)
        return _FakeResponse({"data": {"children": []}})


def _make_ingester(
    classifier: NewsClassifier | None = None,
    subreddits: list[str] | None = None,
    min_score: int = 5,
) -> RedditIngester:
    redis_mock = MagicMock()
    return RedditIngester(
        redis=redis_mock,
        classifier=classifier or FakeClassifier(),
        entity_id="BTC",
        subreddits=subreddits or ["Bitcoin", "CryptoMarkets"],
        interval_s=1800,
        limit_per_sub=50,
        min_score=min_score,
    )


# =============================================================================
# _filter_post — filtres conservateurs ADR-009
# =============================================================================


def test_filter_post_stickied_rejected():
    post = {"stickied": True, "over_18": False, "score": 100}
    assert RedditIngester._filter_post(post, min_score=5) is False


def test_filter_post_nsfw_rejected():
    post = {"stickied": False, "over_18": True, "score": 100}
    assert RedditIngester._filter_post(post, min_score=5) is False


def test_filter_post_low_score_rejected():
    post = {"stickied": False, "over_18": False, "score": 3}
    assert RedditIngester._filter_post(post, min_score=5) is False


def test_filter_post_at_min_score_accepted():
    """Le post au seuil exact est accepté (>=, pas >)."""
    post = {"stickied": False, "over_18": False, "score": 5}
    assert RedditIngester._filter_post(post, min_score=5) is True


def test_filter_post_high_score_accepted():
    post = {"stickied": False, "over_18": False, "score": 1000}
    assert RedditIngester._filter_post(post, min_score=5) is True


def test_filter_post_invalid_score_rejected():
    """Un score non-numérique → False (pas de crash)."""
    post = {"stickied": False, "over_18": False, "score": "not-a-number"}
    assert RedditIngester._filter_post(post, min_score=5) is False


def test_filter_post_missing_score_rejected():
    """Un score manquant → 0 par défaut → rejeté."""
    post = {"stickied": False, "over_18": False}
    assert RedditIngester._filter_post(post, min_score=5) is False


def test_filter_post_custom_min_score():
    """Le filtre est paramétrable au niveau de l'ingester."""
    post = {"stickied": False, "over_18": False, "score": 30}
    assert RedditIngester._filter_post(post, min_score=50) is False
    assert RedditIngester._filter_post(post, min_score=20) is True


# =============================================================================
# _verdict_to_value — mapping classifier output → trinaire
# =============================================================================


@pytest.mark.parametrize(
    "n_bull, n_bear, expected",
    [
        (1, 0, 1),    # bull strict
        (0, 1, -1),   # bear strict
        (0, 0, 0),    # neutral (rien classifié)
        (1, 1, 0),    # ambigu (clipping symétrique en cas de tie)
        (2, 1, 1),    # plus de bull que bear
        (1, 2, -1),   # plus de bear que bull
    ],
)
def test_verdict_to_value(n_bull, n_bear, expected):
    assert RedditIngester._verdict_to_value(n_bull, n_bear) == expected


# =============================================================================
# _fetch_sub — fetch d'un sub (succès / erreur)
# =============================================================================


async def test_fetch_sub_returns_children_on_success():
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(
        responses_by_sub={"Bitcoin": REDDIT_FIXTURE_BITCOIN}
    )
    children = await ing._fetch_sub(client, "Bitcoin")
    assert children is not None
    # Le fixture contient 6 posts bruts (filtres appliqués plus tard dans _fetch)
    assert len(children) == 6


async def test_fetch_sub_returns_none_on_http_error():
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(raise_exc=httpx.ConnectError("network down"))
    children = await ing._fetch_sub(client, "Bitcoin")
    assert children is None


async def test_fetch_sub_returns_none_on_invalid_payload():
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(responses_by_sub={"Bitcoin": {"unexpected": "shape"}})
    children = await ing._fetch_sub(client, "Bitcoin")
    assert children is None


async def test_fetch_sub_returns_none_on_404_status():
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)

    class _NotFoundClient:
        async def get(self, url, **kwargs):
            return _FakeResponse({}, status_code=404)

    children = await ing._fetch_sub(_NotFoundClient(), "BannedSubReddit")
    assert children is None


async def test_fetch_sub_uses_user_agent_header():
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(responses_by_sub={"Bitcoin": REDDIT_FIXTURE_BITCOIN})
    await ing._fetch_sub(client, "Bitcoin")
    assert len(client.calls) == 1
    _, kwargs = client.calls[0]
    headers = kwargs.get("headers", {})
    assert "User-Agent" in headers
    # Le UA doit suivre la convention Reddit (cf. ADR-009)
    assert "tik" in headers["User-Agent"].lower()


# =============================================================================
# _fetch — pipeline complet : multi-sub, filtres, pondération log, agrégation
# =============================================================================


async def test_fetch_aggregates_two_subs_and_filters_correctly():
    """Pipeline complet : 6 posts Bitcoin + 2 posts CryptoMarkets, filtres
    appliqués, classifier appelé sur les posts gardés uniquement."""
    classifier = FakeClassifier(default=(0, 0))  # tout neutre par défaut
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(
        responses_by_sub={
            "Bitcoin": REDDIT_FIXTURE_BITCOIN,
            "CryptoMarkets": REDDIT_FIXTURE_CRYPTOMARKETS,
        }
    )

    payload = await ing._fetch(client)

    assert payload is not None
    # Filtres : sur 6 posts Bitcoin, on retire stickied, score<5, NSFW → 3 gardés
    # Sur 2 posts CryptoMarkets, tous gardés (score>=5, pas stickied/NSFW) → 2 gardés
    # Total = 5 posts classifiés
    assert payload["n_articles"] == 5
    # Tous neutres avec FakeClassifier(default=(0,0))
    assert payload["n_neutral"] == 5
    assert payload["n_bullish"] == 0
    assert payload["n_bearish"] == 0
    # Score net = 0 (tous neutres)
    assert payload["score"] == 0.0
    # Source label
    assert payload["source"] == "reddit_btc"
    assert payload["method"] == "fake"
    # top_subreddits doit refléter la distribution
    top_names = {s["name"] for s in payload["top_subreddits"]}
    assert top_names == {"Bitcoin", "CryptoMarkets"}


async def test_fetch_classifier_only_called_on_filtered_posts():
    """Le classifier ne reçoit que les posts qui passent les filtres."""
    classifier = FakeClassifier(default=(0, 0))
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(
        responses_by_sub={"Bitcoin": REDDIT_FIXTURE_BITCOIN}
    )
    await ing._fetch(client)

    # 6 posts dans le fixture, 3 filtrés → 3 appels
    assert len(classifier.calls) == 3
    # Le post stickied, le score=2 et le NSFW ne doivent PAS apparaître
    titles = " | ".join(classifier.calls)
    assert "Daily discussion" not in titles
    assert "hodling forever" not in titles
    assert "[NSFW]" not in titles


async def test_fetch_log_weighting_amplifies_high_upvote_posts():
    """Pondération log(score+1) : un post bear à 1000 upvotes domine
    un post bull à 5 upvotes → score net négatif clair."""
    classifier = FakeClassifier(
        verdicts_by_title={
            "Bull post low engagement": (1, 0),  # bull
            "Bear post viral": (0, 1),  # bear
        }
    )
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(
        responses_by_sub={
            "Bitcoin": _make_listing(
                [
                    _make_post("Bull post low engagement", score=5),
                    _make_post("Bear post viral", score=1000),
                ]
            )
        }
    )

    payload = await ing._fetch(client)
    assert payload is not None
    # weight_bear = log(1001) ≈ 6.91 ; weight_bull = log(6) ≈ 1.79
    # score = (-1 × 6.91 + 1 × 1.79) / (6.91 + 1.79) ≈ -0.589
    expected = (
        -1 * math.log(1001) + 1 * math.log(6)
    ) / (math.log(1001) + math.log(6))
    assert payload["score"] == pytest.approx(round(expected, 4), abs=0.001)
    # Le bias dérivé sera donc strong_bearish (≤ -0.4) malgré l'égalité 1 bull / 1 bear
    assert payload["score"] <= -0.4


async def test_fetch_log_weighting_balanced_returns_zero():
    """Posts bull et bear avec mêmes upvotes → score = 0 (poids identiques)."""
    classifier = FakeClassifier(
        verdicts_by_title={
            "Bull A": (1, 0),
            "Bull B": (1, 0),
            "Bear A": (0, 1),
            "Bear B": (0, 1),
        }
    )
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(
        responses_by_sub={
            "Bitcoin": _make_listing(
                [
                    _make_post("Bull A", score=100),
                    _make_post("Bull B", score=100),
                    _make_post("Bear A", score=100),
                    _make_post("Bear B", score=100),
                ]
            )
        }
    )
    payload = await ing._fetch(client)
    assert payload is not None
    assert payload["score"] == 0.0
    assert payload["n_bullish"] == 2
    assert payload["n_bearish"] == 2


async def test_fetch_resilient_to_one_sub_failing():
    """Si un sub fail, l'autre continue à contribuer au score."""
    classifier = FakeClassifier(default=(1, 0))  # tout bull
    ing = _make_ingester(classifier=classifier)

    class _PartialClient:
        def __init__(self):
            self.calls = []

        async def get(self, url, **kwargs):
            self.calls.append(url)
            if "Bitcoin" in url:
                return _FakeResponse(REDDIT_FIXTURE_BITCOIN)
            # CryptoMarkets fail
            raise httpx.ConnectError("CryptoMarkets unreachable")

    payload = await ing._fetch(_PartialClient())
    assert payload is not None
    # Seuls les posts Bitcoin filtrés sont classifiés (3 posts)
    assert payload["n_articles"] == 3
    assert payload["n_bullish"] == 3


async def test_fetch_resets_classifier_circuit_breaker():
    classifier = FakeClassifier(default=(0, 0))
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(
        responses_by_sub={
            "Bitcoin": REDDIT_FIXTURE_BITCOIN,
            "CryptoMarkets": REDDIT_FIXTURE_CRYPTOMARKETS,
        }
    )
    await ing._fetch(client)
    assert classifier.reset_calls == 1

    await ing._fetch(client)
    assert classifier.reset_calls == 2


async def test_fetch_returns_none_when_all_filtered():
    """Si tous les posts sont filtrés (stickied/score faible/NSFW), on retourne None."""
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    fixture_all_rejected = _make_listing(
        [
            _make_post("Sticky", score=500, stickied=True),
            _make_post("NSFW", score=500, over_18=True),
            _make_post("Low score", score=2),
        ]
    )
    client = _FakeClient(responses_by_sub={"Bitcoin": fixture_all_rejected})
    ing.subreddits = ["Bitcoin"]
    payload = await ing._fetch(client)
    assert payload is None
    # Le classifier ne doit pas avoir été appelé
    assert classifier.calls == []


async def test_fetch_returns_none_when_all_subs_fail():
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(raise_exc=httpx.ConnectError("network down"))
    payload = await ing._fetch(client)
    assert payload is None


async def test_fetch_top_subreddits_distribution_correct():
    """top_subreddits doit refléter la distribution post-filtrage."""
    classifier = FakeClassifier(default=(0, 0))
    ing = _make_ingester(classifier=classifier)
    client = _FakeClient(
        responses_by_sub={
            "Bitcoin": REDDIT_FIXTURE_BITCOIN,
            "CryptoMarkets": REDDIT_FIXTURE_CRYPTOMARKETS,
        }
    )
    payload = await ing._fetch(client)
    assert payload is not None
    # 3 Bitcoin filtered + 2 CryptoMarkets = top doit avoir Bitcoin > CryptoMarkets
    counts = {s["name"]: s["count"] for s in payload["top_subreddits"]}
    assert counts.get("Bitcoin") == 3
    assert counts.get("CryptoMarkets") == 2


async def test_fetch_skips_non_t3_kind():
    """Reddit peut retourner des objets `kind: "t1"` (commentaires) → ignorés."""
    classifier = FakeClassifier(default=(1, 0))
    ing = _make_ingester(classifier=classifier)
    fixture_mixed_kinds = _make_listing(
        [
            _make_post("Real post 1", score=100),
            _make_post("Comment object", score=100, kind="t1"),  # à ignorer
            _make_post("Real post 2", score=100),
        ]
    )
    client = _FakeClient(responses_by_sub={"Bitcoin": fixture_mixed_kinds})
    ing.subreddits = ["Bitcoin"]
    payload = await ing._fetch(client)
    assert payload is not None
    assert payload["n_articles"] == 2  # Le t1 est ignoré


# =============================================================================
# Constantes et lifecycle
# =============================================================================


def test_redis_key_template():
    assert REDIS_KEY_TPL.format(entity="btc") == "tik.sentiment.reddit.btc"


def test_ingester_name_and_layer():
    ing = _make_ingester()
    assert ing.name == "reddit_ingester"
    assert ing.layer == 6


async def test_stop_calls_classifier_aclose():
    classifier = FakeClassifier()
    ing = _make_ingester(classifier=classifier)
    await ing.stop()
    assert classifier.aclose_called is True
