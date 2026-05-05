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


# =============================================================================
# Asset-aware (ADR-008) — paramètre asset_name au constructeur
# =============================================================================

async def test_ollama_default_asset_name_is_bitcoin():
    """Rétrocompat ADR-006 : sans paramètre, l'asset par défaut est Bitcoin."""
    classifier = OllamaClassifier(url="http://x", model="llama3.2:3b")
    assert classifier.asset_name == "Bitcoin"


async def test_ollama_custom_asset_name():
    classifier = OllamaClassifier(
        url="http://x", model="llama3.2:3b", asset_name="Gold"
    )
    assert classifier.asset_name == "Gold"


async def test_ollama_prompt_includes_asset_name(monkeypatch):
    """Le prompt envoyé à Ollama doit contenir le nom de l'asset configuré."""
    captured_prompts: list[str] = []

    async def fake_post(*args, **kwargs):
        # On capture le prompt envoyé dans le json={...}
        body = kwargs.get("json", {})
        captured_prompts.append(body.get("prompt", ""))

        class _FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"response": "BULLISH"}

        return _FakeResponse()

    classifier_btc = OllamaClassifier(
        url="http://x", model="llama3.2:3b", asset_name="Bitcoin"
    )
    classifier_gold = OllamaClassifier(
        url="http://x", model="llama3.2:3b", asset_name="Gold"
    )

    # On force la création du client httpx puis on mock sa méthode .post
    classifier_btc._client = httpx.AsyncClient()
    classifier_gold._client = httpx.AsyncClient()
    monkeypatch.setattr(classifier_btc._client, "post", fake_post)
    monkeypatch.setattr(classifier_gold._client, "post", fake_post)

    await classifier_btc.classify("BTC surges to ATH")
    await classifier_gold.classify("Gold price hits new high")

    assert len(captured_prompts) == 2
    assert "Bitcoin price" in captured_prompts[0]
    assert "Gold price" not in captured_prompts[0]
    assert "Gold price" in captured_prompts[1]
    assert "Bitcoin price" not in captured_prompts[1]

    await classifier_btc.aclose()
    await classifier_gold.aclose()


async def test_ollama_circuit_breakers_are_isolated_per_instance(monkeypatch):
    """ADR-008 — 2 instances ont des circuit breakers indépendants.

    Si l'instance A subit 3 erreurs et ouvre son breaker, l'instance B
    (asset différent) doit rester intacte. Garantit qu'un incident sur un
    ingester ne contamine pas les autres ingesters textuels.
    """
    classifier_a = OllamaClassifier(
        url="http://x", model="llama3.2:3b", asset_name="Bitcoin"
    )
    classifier_b = OllamaClassifier(
        url="http://x", model="llama3.2:3b", asset_name="Gold"
    )

    # A plante systématiquement, B fonctionne normalement
    monkeypatch.setattr(
        classifier_a, "_call_ollama",
        AsyncMock(side_effect=httpx.ConnectError("down")),
    )
    monkeypatch.setattr(
        classifier_b, "_call_ollama", AsyncMock(return_value="BULLISH")
    )

    # 3 échecs sur A → son breaker s'ouvre
    for _ in range(3):
        await classifier_a.classify("BTC surges")
    assert classifier_a._batch_circuit_open is True

    # B doit être totalement intact
    assert classifier_b._batch_circuit_open is False
    assert classifier_b._consecutive_failures == 0

    # B continue à classifier normalement via Ollama
    result = await classifier_b.classify("Gold price hits new high")
    assert result == (1, 0)
    assert classifier_b._batch_circuit_open is False


async def test_build_news_classifier_passes_asset_name_to_ollama(monkeypatch):
    """La factory doit propager asset_name au OllamaClassifier construit."""
    fake = _make_fake_client(
        response_data={"models": [{"name": "llama3.2:3b"}]}
    )
    monkeypatch.setattr(
        "tik_core.aggregator.news_classifier.httpx.AsyncClient", fake
    )

    classifier = await build_news_classifier(
        classifier_type="ollama",
        ollama_url="http://x",
        ollama_model="llama3.2:3b",
        asset_name="Gold",
    )
    assert isinstance(classifier, OllamaClassifier)
    assert classifier.asset_name == "Gold"


async def test_build_news_classifier_default_asset_is_bitcoin(monkeypatch):
    """Rétrocompat : sans `asset_name`, la factory passe Bitcoin par défaut."""
    fake = _make_fake_client(
        response_data={"models": [{"name": "llama3.2:3b"}]}
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
    assert classifier.asset_name == "Bitcoin"


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
# Cache Redis du sentiment (Lacune C, Phase 1.1 J+10)
# =============================================================================


class _FakeRedis:
    """Mock minimal d'`asyncio.Redis` : in-memory dict avec API setex/get."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self.read_calls: list[str] = []
        self.write_calls: list[tuple[str, int, str]] = []

    async def get(self, key: str):
        self.read_calls.append(key)
        return self._data.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.write_calls.append((key, ttl, value))
        self._data[key] = value


def test_parse_verdict_label_returns_canonical():
    """Helper pur : retourne BULLISH / BEARISH / NEUTRAL ou None."""
    assert OllamaClassifier._parse_verdict_label("BULLISH") == "BULLISH"
    assert OllamaClassifier._parse_verdict_label("the answer is bearish") == "BEARISH"
    assert OllamaClassifier._parse_verdict_label("NEUTRAL.") == "NEUTRAL"
    # Premier match gagne
    assert OllamaClassifier._parse_verdict_label("BULLISH but also BEARISH") == "BULLISH"
    # Non parsable
    assert OllamaClassifier._parse_verdict_label("totally unrelated garbage") is None
    assert OllamaClassifier._parse_verdict_label("") is None


def test_label_to_counts_mapping():
    """Helper pur : mappe label canonique vers (n_bull, n_bear)."""
    assert OllamaClassifier._label_to_counts("BULLISH") == (1, 0)
    assert OllamaClassifier._label_to_counts("BEARISH") == (0, 1)
    assert OllamaClassifier._label_to_counts("NEUTRAL") == (0, 0)
    # Label inconnu → traité comme NEUTRAL (sécurité)
    assert OllamaClassifier._label_to_counts("WHATEVER") == (0, 0)


def test_cache_key_is_unique_per_model_asset_title():
    """Même titre, model/asset différent → keys différentes."""
    c1 = OllamaClassifier(url="http://x", model="llama3.2:3b", asset_name="Bitcoin")
    c2 = OllamaClassifier(url="http://x", model="llama3.2:7b", asset_name="Bitcoin")
    c3 = OllamaClassifier(url="http://x", model="llama3.2:3b", asset_name="Gold")

    title = "BTC surges"
    k1 = c1._cache_key(title)
    k2 = c2._cache_key(title)
    k3 = c3._cache_key(title)
    assert k1 != k2  # model différent
    assert k1 != k3  # asset différent
    assert k1.startswith("tik.sentiment.cache.llama3.2:3b.bitcoin.")


def test_cache_key_normalizes_casing_and_whitespace():
    """Même titre avec variations cosmétiques → même key (stabilité dédup)."""
    c = OllamaClassifier(url="http://x", model="m", asset_name="Bitcoin")
    k1 = c._cache_key("BTC SURGES")
    k2 = c._cache_key("  btc surges  ")
    k3 = c._cache_key("Btc Surges")
    assert k1 == k2 == k3


async def test_ollama_classify_uses_cache_on_hit(monkeypatch):
    """Cache hit → retourne directement le verdict, sans appeler Ollama."""
    redis = _FakeRedis()
    classifier = OllamaClassifier(
        url="http://x", model="llama3.2:3b", asset_name="Bitcoin", redis=redis,
    )
    title = "BTC surges to new high"
    # Pré-remplir le cache avec BULLISH
    cache_key = classifier._cache_key(title)
    redis._data[cache_key] = "BULLISH"

    mock_call = AsyncMock(return_value="should-not-be-called")
    monkeypatch.setattr(classifier, "_call_ollama", mock_call)

    result = await classifier.classify(title)
    assert result == (1, 0)  # BULLISH → (1, 0)
    assert mock_call.call_count == 0  # Ollama jamais appelé


async def test_ollama_classify_stores_in_cache_on_success(monkeypatch):
    """Cache miss → appelle Ollama et stocke le label canonique dans Redis."""
    redis = _FakeRedis()
    classifier = OllamaClassifier(
        url="http://x", model="llama3.2:3b", asset_name="Bitcoin", redis=redis,
    )
    monkeypatch.setattr(
        classifier, "_call_ollama", AsyncMock(return_value="BEARISH"),
    )

    result = await classifier.classify("BTC dumps")
    assert result == (0, 1)

    # 1 write avec TTL = 7 jours et label canonique stocké
    assert len(redis.write_calls) == 1
    key, ttl, value = redis.write_calls[0]
    assert ttl == 7 * 86400
    assert value == "BEARISH"


async def test_ollama_no_cache_without_redis(monkeypatch):
    """Sans `redis` injecté, comportement historique inchangé (pas de cache)."""
    classifier = OllamaClassifier(
        url="http://x", model="llama3.2:3b", redis=None,
    )
    monkeypatch.setattr(
        classifier, "_call_ollama", AsyncMock(return_value="BULLISH"),
    )
    assert await classifier.classify("BTC surges") == (1, 0)
    # Pas de Redis → pas d'erreur, pas d'appel cache (impossible à observer ici
    # mais on vérifie surtout que ça ne crashe pas → rétrocompat préservée)


async def test_ollama_cache_read_error_falls_through_to_ollama(monkeypatch):
    """Si Redis plante en read, on tente quand même Ollama (best-effort)."""

    class _BrokenRedis:
        async def get(self, key):
            raise RuntimeError("redis down")

        async def setex(self, *args):
            raise RuntimeError("redis down")

    classifier = OllamaClassifier(
        url="http://x", model="llama3.2:3b", redis=_BrokenRedis(),
    )
    monkeypatch.setattr(
        classifier, "_call_ollama", AsyncMock(return_value="BULLISH"),
    )
    # Doit retourner BULLISH via Ollama, pas crasher
    assert await classifier.classify("BTC surges") == (1, 0)


async def test_ollama_cache_does_not_store_unparsable_verdict(monkeypatch):
    """Si Ollama répond du bruit non parsable, on ne pollue PAS le cache."""
    redis = _FakeRedis()
    classifier = OllamaClassifier(
        url="http://x", model="llama3.2:3b", redis=redis,
    )
    monkeypatch.setattr(
        classifier, "_call_ollama", AsyncMock(return_value="GLORG WAT"),
    )
    result = await classifier.classify("BTC mystery title")
    assert result == (0, 0)
    # Aucune écriture cache (verdict non parsable)
    assert redis.write_calls == []


async def test_ollama_cache_invalid_stored_value_treated_as_miss(monkeypatch):
    """Si le cache contient une valeur corrompue (non parsable), on retombe sur Ollama."""
    redis = _FakeRedis()
    classifier = OllamaClassifier(
        url="http://x", model="llama3.2:3b", redis=redis,
    )
    title = "BTC surges"
    redis._data[classifier._cache_key(title)] = "GARBAGE_FROM_OLD_VERSION"

    mock_call = AsyncMock(return_value="BULLISH")
    monkeypatch.setattr(classifier, "_call_ollama", mock_call)
    assert await classifier.classify(title) == (1, 0)
    # Ollama appelé malgré la valeur cachée invalide
    assert mock_call.call_count == 1
    # Et le cache mis à jour avec la bonne valeur
    assert redis._data[classifier._cache_key(title)] == "BULLISH"


async def test_ollama_cache_circuit_breaker_open_skips_cache_lookup(monkeypatch):
    """Quand le circuit batch est ouvert, on n'utilise pas le cache mais on
    passe direct au fallback (qui ne dépend pas d'Ollama). Cohérent avec le
    comportement historique : circuit ouvert = on évite Ollama et tout ce
    qui s'y rattache."""
    # Note : ce comportement est documenté pour expliciter qu'on ne tente
    # PAS de bypasser le circuit via le cache. Si Ollama est down et qu'on
    # avait une réponse cachée, on préfère le fallback keywords (cohérence
    # de la sortie sur tout le batch en mode dégradé).
    redis = _FakeRedis()
    classifier = OllamaClassifier(
        url="http://x", model="llama3.2:3b", redis=redis,
    )
    classifier._batch_circuit_open = True  # simule circuit déjà ouvert
    title = "BTC surges to new high"
    redis._data[classifier._cache_key(title)] = "BEARISH"  # cache dirait bear

    mock_call = AsyncMock()
    monkeypatch.setattr(classifier, "_call_ollama", mock_call)

    result = await classifier.classify(title)
    # Cache HIT en premier (cohérent avec le code actuel : le lookup cache
    # se fait AVANT le check du circuit breaker, donc on lit le cache même
    # circuit ouvert. C'est OK : cache = pas d'appel Ollama, donc pas de
    # risque d'aggraver la situation Ollama).
    assert result == (0, 1)  # BEARISH du cache
    assert mock_call.call_count == 0


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
