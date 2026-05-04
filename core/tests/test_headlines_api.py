"""Tests unitaires de l'endpoint /headlines/{entity_id} (Phase 1 J+10).

Couvre les helpers purs de `core/src/tik_core/api/headlines.py` :

- `_parse_iso` (Z / +00:00 / naïf / datetime déjà aware / vide / invalide)
- `_normalize_title` (trim, lowercase)
- `_sort_score` (credibility_recency, recency, decay 12h, published_at vs fetched_at)
- `_iter_headlines_from_payload` (extraction, filtres, rétrocompat)
- `_finalize_headlines` (tri, dédup, cap)

Pas de Redis ni de DB : on teste la logique de merge en mémoire. La
validation runtime de l'endpoint complet (HTTP + Redis live) se fait
après restart Docker via `curl /api/v1/headlines/BTC`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import exp

import pytest

from tik_core.api.headlines import (
    DECAY_HOURS,
    NEWS_SOURCE_KEYS,
    _finalize_headlines,
    _iter_headlines_from_payload,
    _normalize_title,
    _parse_iso,
    _sort_score,
)


# =============================================================================
# Helpers de fixture
# =============================================================================


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _make_headline(
    title: str = "BTC surges to ATH",
    *,
    source: str = "google_news_rss",
    credibility: float = 0.70,
    sentiment: str = "bull",
    fetched_at: datetime | None = None,
    published_at: datetime | None = None,
    url: str | None = "https://example.com/btc",
    publisher: str = "Reuters",
) -> dict:
    """Construit un dict headline conforme à la sortie de
    `_iter_headlines_from_payload` (utilisé pour tester `_finalize_headlines`
    et `_sort_score`)."""
    return {
        "title": title,
        "url": url,
        "publisher": publisher,
        "source": source,
        "credibility": credibility,
        "sentiment": sentiment,
        "published_at": published_at,
        "fetched_at": fetched_at or datetime.now(tz=timezone.utc),
    }


# =============================================================================
# _parse_iso
# =============================================================================


def test_parse_iso_with_z_suffix():
    """Le suffixe `Z` (forme courte UTC) est reconnu."""
    dt = _parse_iso("2026-05-04T10:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_parse_iso_with_explicit_offset():
    """Le suffixe `+00:00` est reconnu."""
    dt = _parse_iso("2026-05-04T10:00:00+00:00")
    assert dt is not None
    assert dt.utcoffset().total_seconds() == 0


def test_parse_iso_naive_assumed_utc():
    """Une chaîne ISO sans tzinfo est considérée comme UTC sémantique."""
    dt = _parse_iso("2026-05-04T10:00:00")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_parse_iso_with_other_offset_normalized_to_utc():
    """Un offset non-UTC est converti en UTC."""
    dt = _parse_iso("2026-05-04T12:00:00+02:00")
    assert dt is not None
    assert dt.hour == 10  # 12h CEST = 10h UTC
    assert dt.utcoffset().total_seconds() == 0


def test_parse_iso_returns_none_for_invalid_string():
    assert _parse_iso("not-a-date") is None
    assert _parse_iso("") is None
    assert _parse_iso(None) is None


def test_parse_iso_accepts_already_aware_datetime():
    """Un datetime déjà aware est renvoyé inchangé (post-conversion UTC)."""
    aware = datetime(2026, 5, 4, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    dt = _parse_iso(aware)
    assert dt is not None
    assert dt.hour == 10  # 12 CEST → 10 UTC
    assert dt.tzinfo is not None


def test_parse_iso_wraps_naive_datetime_as_utc():
    """Un datetime naïf est wrappé en UTC."""
    naive = datetime(2026, 5, 4, 10, 0)
    dt = _parse_iso(naive)
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.hour == 10


# =============================================================================
# _normalize_title
# =============================================================================


def test_normalize_title_trim_and_lowercase():
    assert _normalize_title("  BTC SURGES  ") == "btc surges"


def test_normalize_title_already_normalized():
    assert _normalize_title("btc surges") == "btc surges"


# =============================================================================
# _sort_score
# =============================================================================


def test_sort_score_credibility_recency_recent_high_cred_wins():
    """Un titre très récent et très crédible domine."""
    now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    h_recent_high = _make_headline(
        credibility=0.85,
        fetched_at=now - timedelta(minutes=5),
    )
    h_old_low = _make_headline(
        credibility=0.65,
        fetched_at=now - timedelta(hours=20),
    )
    s1 = _sort_score(h_recent_high, now, "credibility_recency")
    s2 = _sort_score(h_old_low, now, "credibility_recency")
    assert s1 > s2


def test_sort_score_recency_pure_ignores_credibility():
    """En mode recency, seul l'âge compte — credibility n'intervient pas."""
    now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    h_recent_low = _make_headline(
        credibility=0.30,
        fetched_at=now - timedelta(minutes=5),
    )
    h_old_high = _make_headline(
        credibility=0.95,
        fetched_at=now - timedelta(hours=2),
    )
    s1 = _sort_score(h_recent_low, now, "recency")
    s2 = _sort_score(h_old_high, now, "recency")
    assert s1 > s2  # le plus récent gagne malgré une faible crédibilité


def test_sort_score_decay_half_life_at_12h():
    """À l'âge d'une demi-vie (12h), le score est cred × exp(-1) ≈ cred × 0.368."""
    now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    h = _make_headline(
        credibility=0.80,
        fetched_at=now - timedelta(hours=DECAY_HOURS),
    )
    score = _sort_score(h, now, "credibility_recency")
    expected = 0.80 * exp(-1)
    assert score == pytest.approx(expected, abs=0.0001)


def test_sort_score_uses_published_at_when_available():
    """Si published_at est dispo, l'âge est calculé depuis publication."""
    now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    # fetched_at récent mais published_at il y a 12h
    h = _make_headline(
        credibility=0.80,
        fetched_at=now - timedelta(minutes=1),
        published_at=now - timedelta(hours=DECAY_HOURS),
    )
    score = _sort_score(h, now, "credibility_recency")
    expected = 0.80 * exp(-1)
    assert score == pytest.approx(expected, abs=0.0001)


def test_sort_score_clamps_negative_age_to_zero():
    """Si fetched_at est dans le futur (clock skew), on clamp à 0 (pas explosion)."""
    now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    h = _make_headline(
        credibility=0.80,
        fetched_at=now + timedelta(hours=1),  # futur
    )
    score = _sort_score(h, now, "credibility_recency")
    # age clampé à 0 → exp(0) = 1 → score = credibility
    assert score == pytest.approx(0.80, abs=0.0001)


# =============================================================================
# _iter_headlines_from_payload
# =============================================================================


def test_iter_headlines_extracts_normal_payload():
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=24)
    payload = {
        "headlines": [
            {
                "title": "BTC ATH",
                "url": "https://example.com/1",
                "publisher": "Reuters",
                "sentiment": "bull",
                "fetched_at": now.isoformat(),
            },
            {
                "title": "BTC dump",
                "url": "https://example.com/2",
                "publisher": "Bloomberg",
                "sentiment": "bear",
                "fetched_at": now.isoformat(),
            },
        ]
    }
    result = _iter_headlines_from_payload(
        payload, "google_news_rss", 0.70, cutoff
    )
    assert len(result) == 2
    assert result[0]["title"] == "BTC ATH"
    assert result[0]["source"] == "google_news_rss"
    assert result[0]["credibility"] == 0.70
    assert result[1]["sentiment"] == "bear"


def test_iter_headlines_returns_empty_for_non_dict_payload():
    """Tolère les payloads non-dict (ex. payload Redis corrompu)."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=24)
    assert _iter_headlines_from_payload([], "x", 0.5, cutoff) == []
    assert _iter_headlines_from_payload(None, "x", 0.5, cutoff) == []
    assert _iter_headlines_from_payload("string", "x", 0.5, cutoff) == []


def test_iter_headlines_returns_empty_when_field_absent():
    """Rétrocompat : payload publié AVANT la feature (pas de champ headlines)."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=24)
    payload = {"score": 0.5, "n_articles": 10}  # ancien format
    assert _iter_headlines_from_payload(payload, "x", 0.5, cutoff) == []


def test_iter_headlines_returns_empty_when_field_not_list():
    """Le champ existe mais n'est pas une liste — corruption potentielle."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=24)
    payload = {"headlines": "not-a-list"}
    assert _iter_headlines_from_payload(payload, "x", 0.5, cutoff) == []


def test_iter_headlines_skips_non_dict_entries():
    """Une entry qui n'est pas un dict est skippée silencieusement."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=24)
    payload = {
        "headlines": [
            "broken-string",
            None,
            {
                "title": "Valid",
                "publisher": "X",
                "sentiment": "neutral",
                "fetched_at": now.isoformat(),
            },
            42,
        ]
    }
    result = _iter_headlines_from_payload(payload, "x", 0.5, cutoff)
    assert len(result) == 1
    assert result[0]["title"] == "Valid"


def test_iter_headlines_skips_empty_title():
    """Une entry sans title (ou title vide après strip) est skippée."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=24)
    payload = {
        "headlines": [
            {"title": "   ", "fetched_at": now.isoformat()},
            {"title": None, "fetched_at": now.isoformat()},
            {
                "title": "Real one",
                "publisher": "X",
                "sentiment": "bull",
                "fetched_at": now.isoformat(),
            },
        ]
    }
    result = _iter_headlines_from_payload(payload, "x", 0.5, cutoff)
    assert len(result) == 1
    assert result[0]["title"] == "Real one"


def test_iter_headlines_filters_by_cutoff():
    """Une entry plus ancienne que cutoff est filtrée."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=24)
    payload = {
        "headlines": [
            {
                "title": "Recent",
                "publisher": "X",
                "sentiment": "bull",
                "fetched_at": now.isoformat(),
            },
            {
                "title": "Too old",
                "publisher": "X",
                "sentiment": "bull",
                "fetched_at": (now - timedelta(hours=48)).isoformat(),
            },
        ]
    }
    result = _iter_headlines_from_payload(payload, "x", 0.5, cutoff)
    assert len(result) == 1
    assert result[0]["title"] == "Recent"


def test_iter_headlines_skips_invalid_fetched_at():
    """fetched_at manquant ou invalide → entry skippée."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=24)
    payload = {
        "headlines": [
            {"title": "No fetched_at", "publisher": "X", "sentiment": "bull"},
            {
                "title": "Invalid fetched_at",
                "publisher": "X",
                "sentiment": "bull",
                "fetched_at": "not-a-date",
            },
            {
                "title": "Valid",
                "publisher": "X",
                "sentiment": "bull",
                "fetched_at": now.isoformat(),
            },
        ]
    }
    result = _iter_headlines_from_payload(payload, "x", 0.5, cutoff)
    assert len(result) == 1
    assert result[0]["title"] == "Valid"


def test_iter_headlines_propagates_credibility_and_source():
    """credibility et source sont écrasés par les arguments du caller."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=24)
    # Entry essaie de spoof credibility/source mais ils doivent être ignorés
    payload = {
        "headlines": [
            {
                "title": "T",
                "publisher": "X",
                "sentiment": "bull",
                "credibility": 0.99,  # spoofé — doit être ignoré
                "source": "spoofed_source",  # spoofé — doit être ignoré
                "fetched_at": now.isoformat(),
            }
        ]
    }
    result = _iter_headlines_from_payload(payload, "real_source", 0.42, cutoff)
    assert len(result) == 1
    assert result[0]["credibility"] == 0.42
    assert result[0]["source"] == "real_source"


# =============================================================================
# _finalize_headlines
# =============================================================================


def test_finalize_empty_input_returns_empty():
    now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    assert _finalize_headlines([], "credibility_recency", 10, now) == []


def test_finalize_sorts_by_credibility_recency_desc():
    """Les titres sont triés par score desc."""
    now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    h1 = _make_headline(title="A", credibility=0.50, fetched_at=now - timedelta(hours=1))
    h2 = _make_headline(title="B", credibility=0.90, fetched_at=now - timedelta(hours=1))
    h3 = _make_headline(title="C", credibility=0.70, fetched_at=now - timedelta(hours=1))
    result = _finalize_headlines([h1, h2, h3], "credibility_recency", 10, now)
    assert [h["title"] for h in result] == ["B", "C", "A"]


def test_finalize_sorts_by_recency_desc():
    """Mode recency : le plus récent en tête, peu importe credibility."""
    now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    h_recent = _make_headline(
        title="Recent low cred",
        credibility=0.30,
        fetched_at=now - timedelta(minutes=2),
    )
    h_old = _make_headline(
        title="Old high cred",
        credibility=0.95,
        fetched_at=now - timedelta(hours=10),
    )
    result = _finalize_headlines([h_old, h_recent], "recency", 10, now)
    assert result[0]["title"] == "Recent low cred"


def test_finalize_dedupes_by_normalized_title():
    """Le même titre relayé sur 2 sources est dédupé (premier dans le tri gagne)."""
    now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    h_high = _make_headline(
        title="BTC surges to ATH",
        source="google_news_rss",
        credibility=0.70,
        fetched_at=now - timedelta(minutes=10),
    )
    h_low = _make_headline(
        title="  btc surges to ath  ",  # même titre normalisé
        source="reddit_btc",
        credibility=0.65,
        fetched_at=now - timedelta(minutes=20),
    )
    result = _finalize_headlines([h_high, h_low], "credibility_recency", 10, now)
    assert len(result) == 1
    assert result[0]["source"] == "google_news_rss"  # première dans le tri = celle gardée


def test_finalize_caps_to_limit():
    """Le nombre de titres retournés ne dépasse pas `limit`."""
    now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    headlines = [
        _make_headline(
            title=f"Title {i}",
            credibility=0.70,
            fetched_at=now - timedelta(minutes=i),
        )
        for i in range(20)
    ]
    result = _finalize_headlines(headlines, "credibility_recency", 5, now)
    assert len(result) == 5
    # Les 5 plus récents (i=0..4) sont gardés
    titles = [h["title"] for h in result]
    assert titles == [f"Title {i}" for i in range(5)]


# =============================================================================
# Constantes
# =============================================================================


def test_news_source_keys_includes_three_expected_sources():
    """Les 3 ingesters cibles Phase 1 sont bien câblés."""
    sources = {s for s, _ in NEWS_SOURCE_KEYS}
    assert sources == {"google_news_rss", "cryptocompare_news", "reddit_btc"}


def test_news_source_keys_use_entity_placeholder():
    """Chaque template Redis a un placeholder {entity} pour le format()."""
    for _, key_tpl in NEWS_SOURCE_KEYS:
        assert "{entity}" in key_tpl
