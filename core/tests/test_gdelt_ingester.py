"""Tests unitaires du GDELT ingester (couche 6 — sentiment news macro/géopol GOLD).

Couvre :
- `_extract_tone_points` (parsing du payload timelinetone)
- `_fetch` complet : succès, erreur HTTP, payload vide / malformé,
  agrégation moyenne sur multiple points
- Construction de l'URL : `sourcelang:<lang>` dans la query
- Lifecycle (start/stop)

Pas de Redis ni de DB : on teste `_fetch` directement, pas la boucle `_run`.
La validation runtime de `_run` (Redis setex + publish) se fait après
restart Docker via vérification de la clé `tik.sentiment.gdelt.gold`.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from tik_core.aggregator.gdelt_ingester import (
    REDIS_KEY_TPL,
    GdeltIngester,
)

# =============================================================================
# Fixtures et helpers
# =============================================================================


def _make_timelinetone_payload(values: list[float | None]) -> dict:
    """Construit un payload GDELT timelinetone avec les valeurs données.

    Format réel GDELT V2 :
    {"timeline": [{"series": "Tone", "data": [{"date": "...", "value": -1.23}, ...]}]}
    """
    return {
        "timeline": [
            {
                "series": "Tone Smoothed",
                "data": [
                    {
                        "date": f"2026050{i}T120000Z",
                        "value": v if v is not None else "n/a",
                    }
                    for i, v in enumerate(values)
                ],
            }
        ]
    }


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
    """Mock minimal d'httpx.AsyncClient."""

    def __init__(
        self,
        json_data: dict | None = None,
        status_code: int = 200,
        raise_exc: Exception | None = None,
    ) -> None:
        self._json = json_data
        self._status = status_code
        self._raise_exc = raise_exc
        self.last_url: str | None = None
        self.last_kwargs: dict | None = None

    async def get(self, url: str, **kwargs):
        self.last_url = url
        self.last_kwargs = kwargs
        if self._raise_exc:
            raise self._raise_exc
        return _FakeResponse(self._json or {}, self._status)


def _make_ingester(
    entity_id: str = "GOLD",
    query: str = '"gold price"',
    lang: str = "eng",
    timespan: str = "1d",
) -> GdeltIngester:
    redis_mock = MagicMock()
    return GdeltIngester(
        redis=redis_mock,
        entity_id=entity_id,
        query=query,
        timespan=timespan,
        lang=lang,
        interval_s=1800,
    )


# =============================================================================
# _extract_tone_points — parsing tolérant
# =============================================================================


def test_extract_tone_points_valid_payload():
    payload = _make_timelinetone_payload([-1.5, -2.3, 0.5, 1.2])
    points = GdeltIngester._extract_tone_points(payload)
    assert points == [-1.5, -2.3, 0.5, 1.2]


def test_extract_tone_points_empty_timeline():
    assert GdeltIngester._extract_tone_points({"timeline": []}) == []


def test_extract_tone_points_missing_timeline_key():
    assert GdeltIngester._extract_tone_points({}) == []


def test_extract_tone_points_timeline_not_list():
    """Un timeline malformé (non-liste) ne crash pas, retourne vide."""
    assert GdeltIngester._extract_tone_points({"timeline": "broken"}) == []


def test_extract_tone_points_filters_invalid_values():
    """Les valeurs non numériques (str, None) sont skip silencieusement."""
    payload = _make_timelinetone_payload([1.0, None, "n/a", 2.5])
    points = GdeltIngester._extract_tone_points(payload)
    # Seules les valeurs numériques sont gardées
    assert points == [1.0, 2.5]


def test_extract_tone_points_multiple_series():
    """GDELT peut renvoyer plusieurs séries (ex Tone + Tone Smoothed) — on les agrège toutes."""
    payload = {
        "timeline": [
            {
                "series": "Tone",
                "data": [{"date": "x", "value": -1.0}, {"date": "y", "value": -2.0}],
            },
            {
                "series": "Tone Smoothed",
                "data": [{"date": "x", "value": -1.5}],
            },
        ]
    }
    points = GdeltIngester._extract_tone_points(payload)
    assert sorted(points) == [-2.0, -1.5, -1.0]


def test_extract_tone_points_skips_malformed_series():
    """Une série non-dict est ignorée."""
    payload = {
        "timeline": [
            {"series": "Tone", "data": [{"value": -1.0}]},
            "not-a-dict",  # malformée
            {"series": "Other", "data": [{"value": 2.0}]},
        ]
    }
    points = GdeltIngester._extract_tone_points(payload)
    assert sorted(points) == [-1.0, 2.0]


def test_extract_tone_points_skips_malformed_data_entries():
    """Une entrée non-dict dans data est ignorée."""
    payload = {
        "timeline": [
            {
                "series": "Tone",
                "data": [
                    {"value": 1.0},
                    "not-a-dict",
                    {"value": 2.0},
                ],
            }
        ]
    }
    points = GdeltIngester._extract_tone_points(payload)
    assert sorted(points) == [1.0, 2.0]


def test_extract_tone_points_data_field_not_list():
    """Si le champ data n'est pas une liste, série ignorée."""
    payload = {"timeline": [{"series": "Tone", "data": "broken"}]}
    assert GdeltIngester._extract_tone_points(payload) == []


# =============================================================================
# _fetch — pipeline complet
# =============================================================================


async def test_fetch_with_valid_payload_returns_average_tone():
    payload = _make_timelinetone_payload([-1.0, -2.0, -3.0, 0.0])
    ing = _make_ingester()
    client = _FakeClient(json_data=payload)

    result = await ing._fetch(client)

    assert result is not None
    assert result["source"] == "gdelt_news"
    assert result["method"] == "gdelt_tone_v2"
    assert result["entity_id"] == "GOLD"
    assert result["query"] == '"gold price"'
    assert result["lang"] == "eng"
    assert result["timespan"] == "1d"
    # Moyenne de [-1, -2, -3, 0] = -1.5
    assert result["tone"] == -1.5
    assert result["n_points"] == 4
    assert "fetched_at" in result


async def test_fetch_aggregates_correctly_with_mixed_signs():
    payload = _make_timelinetone_payload([2.0, 1.0, -1.0, -2.0])
    ing = _make_ingester()
    client = _FakeClient(json_data=payload)

    result = await ing._fetch(client)
    assert result is not None
    # Moyenne de [2, 1, -1, -2] = 0.0
    assert result["tone"] == 0.0


async def test_fetch_returns_none_on_empty_timeline():
    ing = _make_ingester()
    client = _FakeClient(json_data={"timeline": []})
    assert await ing._fetch(client) is None


async def test_fetch_returns_none_on_no_valid_points():
    """Tous les points sont des sentinelles non numériques → None."""
    payload = _make_timelinetone_payload([None, None, None])
    ing = _make_ingester()
    client = _FakeClient(json_data=payload)
    assert await ing._fetch(client) is None


async def test_fetch_returns_none_on_http_error():
    ing = _make_ingester()
    client = _FakeClient(raise_exc=httpx.ConnectError("network unreachable"))
    assert await ing._fetch(client) is None


async def test_fetch_returns_none_on_4xx_status():
    ing = _make_ingester()
    client = _FakeClient(json_data={}, status_code=404)
    assert await ing._fetch(client) is None


async def test_fetch_returns_none_on_5xx_status():
    ing = _make_ingester()
    client = _FakeClient(json_data={}, status_code=503)
    assert await ing._fetch(client) is None


async def test_fetch_returns_none_on_malformed_json():
    """Payload sans champ timeline → None."""
    ing = _make_ingester()
    client = _FakeClient(json_data={"unexpected": "shape"})
    assert await ing._fetch(client) is None


async def test_fetch_query_includes_sourcelang_filter():
    """La langue se filtre dans la query via sourcelang:<lang> (cf. GDELT V2 doc)."""
    payload = _make_timelinetone_payload([0.0])
    ing = _make_ingester(query='"gold price"', lang="eng")
    client = _FakeClient(json_data=payload)

    await ing._fetch(client)
    assert client.last_kwargs is not None
    params = client.last_kwargs.get("params", {})
    assert params.get("query") == '"gold price" sourcelang:eng'
    assert params.get("mode") == "timelinetone"
    assert params.get("format") == "json"
    assert params.get("timespan") == "1d"


async def test_fetch_query_with_custom_lang():
    payload = _make_timelinetone_payload([0.0])
    ing = _make_ingester(query="oil price", lang="fra")
    client = _FakeClient(json_data=payload)
    await ing._fetch(client)
    params = client.last_kwargs.get("params", {})
    assert params.get("query") == "oil price sourcelang:fra"


async def test_fetch_uses_user_agent_header():
    payload = _make_timelinetone_payload([0.0])
    ing = _make_ingester()
    client = _FakeClient(json_data=payload)
    await ing._fetch(client)
    headers = client.last_kwargs.get("headers", {})
    assert "User-Agent" in headers


async def test_fetch_extreme_negative_tone_preserved():
    """Tone extrêmement négatif (tensions max) doit être préservé tel quel."""
    payload = _make_timelinetone_payload([-8.5, -9.0])
    ing = _make_ingester()
    client = _FakeClient(json_data=payload)

    result = await ing._fetch(client)
    assert result is not None
    assert result["tone"] == -8.75


async def test_fetch_tolerates_some_invalid_points():
    """Mix de valid et invalid → on agrège seulement les valides."""
    payload = _make_timelinetone_payload([1.0, None, 3.0, "n/a", 5.0])
    ing = _make_ingester()
    client = _FakeClient(json_data=payload)

    result = await ing._fetch(client)
    assert result is not None
    # Moyenne de [1, 3, 5] = 3.0
    assert result["tone"] == 3.0
    assert result["n_points"] == 3


# =============================================================================
# Constantes et lifecycle
# =============================================================================


def test_redis_key_template():
    assert REDIS_KEY_TPL.format(entity="gold") == "tik.sentiment.gdelt.gold"
    assert REDIS_KEY_TPL.format(entity="btc") == "tik.sentiment.gdelt.btc"


def test_ingester_name_and_layer():
    ing = _make_ingester()
    assert ing.name == "gdelt_ingester"
    assert ing.layer == 6


def test_ingester_has_no_classifier_attribute():
    """ADR-010 — GDELT n'utilise PAS Ollama, le ingester n'a donc pas de classifier."""
    ing = _make_ingester()
    assert not hasattr(ing, "classifier")


async def test_stop_does_not_crash_without_classifier():
    """Le stop ne doit pas tenter d'aclose un classifier inexistant."""
    ing = _make_ingester()
    # Pas de start() lancé, juste stop direct
    await ing.stop()  # ne doit pas lever
