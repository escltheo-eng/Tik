"""Tests unitaires des classifieurs de sentiment de news.

Couvre :
- KeywordClassifier (analyse par mots-clés) — équivalent de l'ancien
  test_cryptocompare_ingester.py, migré tel quel.
- OllamaClassifier (LLM local) — mocké via unittest.mock.AsyncMock.
- build_news_classifier (factory + ping de santé Ollama) — mocké via
  monkeypatch de httpx.AsyncClient.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from tik_core.aggregator.news_classifier import (
    BEARISH_KEYWORDS,
    BULLISH_KEYWORDS,
    KeywordClassifier,
    OllamaClassifier,
    build_news_classifier,
)


# ----- KeywordClassifier : titres clairement directionnels -----

@pytest.mark.parametrize(
    "title, expected_bull, expected_bear",
    [
        # Bull simples
        ("Bitcoin surges to ATH", 2, 0),  # surges + ath
        ("BTC rally continues", 1, 0),
        ("Major partnership boosts adoption", 3, 0),  # partnership + boosts + adoption
        ("Bottoming Signals as Macro Risks Ease", 2, 1),  # bottoming + ease vs risks
        # Bear simples — note : "bear-market" reste un seul token (tiret interne
        # gardé par le regex), donc "bear" exact ne matche pas. Limitation
        # documentée du tokenizer keywords.
        ("Bitcoin crashes to bear-market lows", 0, 1),  # crashes seulement
        ("Massive sell-off triggers panic", 0, 2),  # sell-off + panic
        ("Coinbase premium turns negative as BTC sees sell-off", 0, 1),  # sell-off
        ("Government bans crypto trading", 0, 1),  # bans
        # Mixtes (les deux comptes)
        ("BTC rallies despite bearish headlines", 1, 1),
        ("Recovery stalls amid concerns", 1, 1),  # recovery + concerns
    ],
)
async def test_keyword_classifier_directional(title, expected_bull, expected_bear):
    n_bull, n_bear = await KeywordClassifier().classify(title)
    assert n_bull == expected_bull, f"bull mismatch on '{title}'"
    assert n_bear == expected_bear, f"bear mismatch on '{title}'"


# ----- Casse insensible -----

async def test_keyword_classifier_case_insensitive():
    classifier = KeywordClassifier()
    n_bull, n_bear = await classifier.classify("BTC SURGES TO RECORD HIGH")
    assert n_bull >= 2  # SURGES + RECORD + HIGH (3 attendus)

    n_bull2, n_bear2 = await classifier.classify("btc surges to record high")
    assert (n_bull, n_bear) == (n_bull2, n_bear2)


# ----- Cas limites -----

async def test_keyword_classifier_empty_string():
    assert await KeywordClassifier().classify("") == (0, 0)


async def test_keyword_classifier_none():
    # classify doit gérer None sans crasher
    assert await KeywordClassifier().classify(None) == (0, 0)


async def test_keyword_classifier_only_neutral_words():
    n_bull, n_bear = await KeywordClassifier().classify(
        "Bitcoin price moves sideways today"
    )
    assert n_bull == 0
    assert n_bear == 0


async def test_keyword_classifier_dedup_within_title():
    # Le même mot apparaît plusieurs fois → ne compte qu'une fois
    # (set d'intersection dans _classify_sync)
    n_bull, _ = await KeywordClassifier().classify("bull bull bull bullish bullish")
    # bull (1 mot unique) + bullish (1 mot unique) = 2 matchs
    assert n_bull == 2


async def test_keyword_classifier_punctuation():
    # Les apostrophes et tirets internes sont gardés, le reste est délimité
    n_bull, n_bear = await KeywordClassifier().classify(
        "BTC's surge: a record? Yes!"
    )
    # surge + record = 2 bull, 0 bear
    assert n_bull >= 2
    assert n_bear == 0


# ----- Mots ajoutés lors de l'enrichissement 2026-04-29 -----

@pytest.mark.parametrize(
    "title, expected_bull, expected_bear",
    [
        # Bull ajoutés
        ("Institutions accumulate Bitcoin amid uncertainty", 1, 0),  # accumulate
        ("Crypto markets show bottoming signals", 1, 0),  # bottoming
        ("Inflation eases, optimism grows", 2, 0),  # eases + optimism
        ("Bitcoin gains support at 75k", 2, 0),  # gains + support
        # Bear ajoutés
        ("Fed lowers growth forecast", 0, 1),  # lowers
        ("Major lawsuit filed against exchange", 0, 1),  # lawsuit
        ("Founder arrested on fraud charges", 0, 2),  # arrested + fraud
        ("Exchange shutdown shocks community", 0, 1),  # shutdown
    ],
)
async def test_keyword_classifier_enriched_keywords(title, expected_bull, expected_bear):
    n_bull, n_bear = await KeywordClassifier().classify(title)
    assert n_bull == expected_bull, f"bull mismatch on '{title}'"
    assert n_bear == expected_bear, f"bear mismatch on '{title}'"


# ----- Méthode et hooks de l'interface NewsClassifier -----

async def test_keyword_classifier_method_name():
    assert KeywordClassifier().method_name == "keywords"


async def test_keyword_classifier_reset_batch_is_noop():
    # KeywordClassifier ne porte pas de circuit breaker → reset_batch ne plante pas
    classifier = KeywordClassifier()
    classifier.reset_batch()
    n_bull, n_bear = await classifier.classify("BTC surges")
    assert n_bull == 1
    assert n_bear == 0


async def test_keyword_classifier_aclose_is_noop():
    # KeywordClassifier ne possède pas de ressource HTTP → aclose ne plante pas
    classifier = KeywordClassifier()
    await classifier.aclose()


# ----- Cohérence des listes -----

def test_keyword_lists_no_overlap():
    """Aucun mot ne doit être à la fois dans BULLISH et BEARISH (ambigu)."""
    overlap = BULLISH_KEYWORDS & BEARISH_KEYWORDS
    assert overlap == set(), f"Overlap interdit : {overlap}"


def test_keyword_lists_lowercase():
    """Toutes les entrées doivent être en minuscules (le matching le suppose)."""
    for kw in BULLISH_KEYWORDS:
        assert kw == kw.lower(), f"{kw} pas en minuscules"
    for kw in BEARISH_KEYWORDS:
        assert kw == kw.lower(), f"{kw} pas en minuscules"


def test_keyword_lists_non_empty():
    """Garde-fou : on ne veut jamais tomber à 0 mot par accident."""
    assert len(BULLISH_KEYWORDS) >= 30
    assert len(BEARISH_KEYWORDS) >= 30


# =============================================================================
# OllamaClassifier — parsing pure function (pas de mock nécessaire)
# =============================================================================

@pytest.mark.parametrize(
    "verdict, expected",
    [
        ("BULLISH", (1, 0)),
        ("BEARISH", (0, 1)),
        ("NEUTRAL", (0, 0)),
        # Casse mixte → upper() en interne
        ("bullish", (1, 0)),
        ("Bearish", (0, 1)),
        # Ponctuation / whitespace
        ("BULLISH.", (1, 0)),
        ("BULLISH\n", (1, 0)),
        # Réponse verbeuse → on prend le 1er match
        ("I think this is BULLISH because...", (1, 0)),
        ("My answer: BEARISH outlook", (0, 1)),
        # Réponse incompréhensible → (0, 0) + log warning interne
        ("GLORG", (0, 0)),
        ("", (0, 0)),
    ],
)
def test_ollama_verdict_to_counts(verdict, expected):
    assert OllamaClassifier._verdict_to_counts(verdict, "any title") == expected


def test_ollama_verdict_to_counts_first_match_wins():
    # BEARISH apparaît avant BULLISH → bearish gagne
    assert OllamaClassifier._verdict_to_counts(
        "BEARISH then BULLISH", "any"
    ) == (0, 1)
    # Inverse : BULLISH d'abord
    assert OllamaClassifier._verdict_to_counts(
        "BULLISH not BEARISH", "any"
    ) == (1, 0)
    # NEUTRAL d'abord
    assert OllamaClassifier._verdict_to_counts(
        "NEUTRAL but slightly BULLISH", "any"
    ) == (0, 0)


# =============================================================================
# OllamaClassifier.classify — mock de _call_ollama
# =============================================================================

async def test_ollama_classify_empty_title():
    classifier = OllamaClassifier(url="http://x", model="llama3.2:3b")
    assert await classifier.classify("") == (0, 0)
    assert await classifier.classify(None) == (0, 0)


async def test_ollama_classify_success(monkeypatch):
    classifier = OllamaClassifier(url="http://x", model="llama3.2:3b")
    monkeypatch.setattr(
        classifier, "_call_ollama", AsyncMock(return_value="BULLISH")
    )

    assert await classifier.classify("BTC surges to new high") == (1, 0)


async def test_ollama_classify_falls_back_on_error(monkeypatch):
    """Quand Ollama échoue, on retombe sur les keywords pour ce titre."""
    classifier = OllamaClassifier(url="http://x", model="llama3.2:3b")
    monkeypatch.setattr(
        classifier, "_call_ollama",
        AsyncMock(side_effect=httpx.ConnectError("ollama down")),
    )

    # Titre avec mots-clés bull → fallback keywords devrait matcher
    # ("surges" bull + "high" bull = (2, 0))
    result = await classifier.classify("BTC surges to new high")
    assert result == (2, 0)
    assert classifier._consecutive_failures == 1
    assert classifier._batch_circuit_open is False


async def test_ollama_circuit_breaker_opens_after_3_failures(monkeypatch):
    """3 erreurs successives → circuit ouvert pour le reste du batch.
    Le 4e appel doit utiliser direct le fallback sans tenter Ollama."""
    classifier = OllamaClassifier(url="http://x", model="llama3.2:3b")
    mock_call = AsyncMock(side_effect=httpx.ConnectError("down"))
    monkeypatch.setattr(classifier, "_call_ollama", mock_call)

    # 3 appels qui font échouer Ollama
    for _ in range(3):
        await classifier.classify("BTC surges")

    assert mock_call.call_count == 3
    assert classifier._batch_circuit_open is True

    # 4e appel : circuit ouvert → pas d'appel à Ollama, fallback direct
    result = await classifier.classify("BTC crashes hard")
    assert mock_call.call_count == 3  # inchangé
    assert result == (0, 1)  # "crashes" matche bear


async def test_ollama_reset_batch_rearms_circuit(monkeypatch):
    classifier = OllamaClassifier(url="http://x", model="llama3.2:3b")
    monkeypatch.setattr(
        classifier, "_call_ollama",
        AsyncMock(side_effect=httpx.ConnectError("down")),
    )

    # Ouvre le circuit
    for _ in range(3):
        await classifier.classify("BTC surges")
    assert classifier._batch_circuit_open is True

    # Nouveau cycle → reset
    classifier.reset_batch()
    assert classifier._batch_circuit_open is False
    assert classifier._consecutive_failures == 0


async def test_ollama_success_resets_failure_counter(monkeypatch):
    """Un succès après des erreurs réinitialise le compteur (sans circuit)."""
    classifier = OllamaClassifier(url="http://x", model="llama3.2:3b")

    monkeypatch.setattr(
        classifier, "_call_ollama",
        AsyncMock(side_effect=httpx.ConnectError("transient")),
    )
    await classifier.classify("BTC surges")
    await classifier.classify("BTC surges")
    assert classifier._consecutive_failures == 2

    # Ollama redevient OK
    monkeypatch.setattr(
        classifier, "_call_ollama", AsyncMock(return_value="BULLISH")
    )
    await classifier.classify("BTC surges")
    assert classifier._consecutive_failures == 0


async def test_ollama_method_name_includes_model():
    assert (
        OllamaClassifier(url="http://x", model="llama3.2:3b").method_name
        == "ollama:llama3.2:3b"
    )
    assert (
        OllamaClassifier(url="http://x", model="qwen2.5:7b").method_name
        == "ollama:qwen2.5:7b"
    )


async def test_ollama_unparsable_response_returns_neutral(monkeypatch):
    """Si Ollama répond une string sans BULLISH/BEARISH/NEUTRAL,
    on retourne (0, 0) — pas de fallback keywords (le LLM a répondu,
    juste pas exploitable)."""
    classifier = OllamaClassifier(url="http://x", model="llama3.2:3b")
    monkeypatch.setattr(
        classifier, "_call_ollama", AsyncMock(return_value="GLORG WAT")
    )
    assert await classifier.classify("BTC surges") == (0, 0)


# =============================================================================
# build_news_classifier — factory avec mock de httpx.AsyncClient
# =============================================================================


def _make_fake_client(response_data=None, raise_on_request=None):
    """Crée une classe qui imite httpx.AsyncClient(...) avec context manager."""

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self._response_data = response_data
            self._raise = raise_on_request

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            if self._raise:
                raise self._raise
            r = MagicMock()
            r.raise_for_status = MagicMock()
            r.json = MagicMock(return_value=self._response_data)
            return r

    return _FakeClient


async def test_build_classifier_keywords_type():
    classifier = await build_news_classifier(
        classifier_type="keywords",
        ollama_url="http://x",
        ollama_model="any",
    )
    assert isinstance(classifier, KeywordClassifier)


async def test_build_classifier_ollama_alive_with_model(monkeypatch):
    fake = _make_fake_client(
        response_data={"models": [{"name": "llama3.2:3b"}, {"name": "other:7b"}]}
    )
    monkeypatch.setattr(
        "tik_core.aggregator.news_classifier.httpx.AsyncClient", fake
    )

    classifier = await build_news_classifier(
        classifier_type="ollama",
        ollama_url="http://x",
        ollama_model="llama3.2:3b",
    )
    assert isinstance(classifier, OllamaClassifier)
    assert classifier.model == "llama3.2:3b"


async def test_build_classifier_ollama_unreachable_falls_back(monkeypatch):
    fake = _make_fake_client(
        raise_on_request=httpx.ConnectError("connection refused")
    )
    monkeypatch.setattr(
        "tik_core.aggregator.news_classifier.httpx.AsyncClient", fake
    )

    classifier = await build_news_classifier(
        classifier_type="ollama",
        ollama_url="http://x",
        ollama_model="llama3.2:3b",
    )
    assert isinstance(classifier, KeywordClassifier)


async def test_build_classifier_ollama_alive_but_model_missing(monkeypatch):
    """Ollama répond mais le modèle demandé n'est pas téléchargé."""
    fake = _make_fake_client(
        response_data={"models": [{"name": "other:7b"}]}
    )
    monkeypatch.setattr(
        "tik_core.aggregator.news_classifier.httpx.AsyncClient", fake
    )

    classifier = await build_news_classifier(
        classifier_type="ollama",
        ollama_url="http://x",
        ollama_model="llama3.2:3b",
    )
    assert isinstance(classifier, KeywordClassifier)


async def test_build_classifier_ollama_empty_models_list(monkeypatch):
    """Ollama répond mais la liste des modèles est vide."""
    fake = _make_fake_client(response_data={"models": []})
    monkeypatch.setattr(
        "tik_core.aggregator.news_classifier.httpx.AsyncClient", fake
    )

    classifier = await build_news_classifier(
        classifier_type="ollama",
        ollama_url="http://x",
        ollama_model="llama3.2:3b",
    )
    assert isinstance(classifier, KeywordClassifier)
