"""Tests unitaires du repo de persistance des titres OSINT (Lacune A J+10).

Couvre les helpers purs (`compute_title_hash`, `parse_iso_naive`,
`cutoff_from_hours`, `_build_record`) et le comportement de
`persist_headlines` avec un mock `session_maker`.

Pas de tests d'intégration DB : un mock minimal de `async_sessionmaker`
suffit pour valider que :
- `add_all(records)` est appelé avec les bons records
- `commit()` est appelé
- Les erreurs DB sont avalées (best-effort)

La validation runtime de l'INSERT bout-en-bout se fait après restart Docker.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tik_core.storage.headlines_repo import (
    _build_record,
    compute_title_hash,
    cutoff_from_hours,
    parse_iso_naive,
    persist_headlines,
)
from tik_core.storage.models import HeadlineRecord

# =============================================================================
# compute_title_hash — normalisation + déterminisme
# =============================================================================


def test_compute_title_hash_is_deterministic():
    """Même titre normalisé → même hash."""
    h1 = compute_title_hash("Bitcoin reclaims 80K")
    h2 = compute_title_hash("Bitcoin reclaims 80K")
    assert h1 == h2


def test_compute_title_hash_normalizes_casing():
    """Casing différent → même hash (dédup multi-source)."""
    h1 = compute_title_hash("BITCOIN RECLAIMS 80K")
    h2 = compute_title_hash("bitcoin reclaims 80k")
    h3 = compute_title_hash("Bitcoin Reclaims 80k")
    assert h1 == h2 == h3


def test_compute_title_hash_strips_whitespace():
    """Espaces autour du titre ignorés."""
    h1 = compute_title_hash("  BTC surges  ")
    h2 = compute_title_hash("BTC surges")
    assert h1 == h2


def test_compute_title_hash_returns_16_hex_chars():
    """Hash tronqué à 16 hex chars (cohérent avec cache Lacune C)."""
    h = compute_title_hash("any title here")
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_compute_title_hash_distinct_for_different_titles():
    """Titres différents → hash différents."""
    h1 = compute_title_hash("Bitcoin surges")
    h2 = compute_title_hash("Bitcoin dumps")
    assert h1 != h2


# =============================================================================
# parse_iso_naive — strip tz cohérent avec Bug 9 / publisher.py
# =============================================================================


def test_parse_iso_naive_strips_z_suffix():
    """Le suffixe `Z` est interprété UTC puis strippé."""
    dt = parse_iso_naive("2026-05-04T22:00:00Z")
    assert dt is not None
    assert dt.tzinfo is None  # naïf après strip
    assert dt.hour == 22


def test_parse_iso_naive_strips_explicit_offset():
    """Un offset explicite est converti en UTC puis strippé."""
    dt = parse_iso_naive("2026-05-04T00:00:00+02:00")
    assert dt is not None
    assert dt.tzinfo is None
    # 00h CEST = 22h UTC la veille
    assert dt.hour == 22
    assert dt.day == 3


def test_parse_iso_naive_handles_already_naive():
    """Une chaîne ISO déjà naïve est renvoyée telle quelle."""
    dt = parse_iso_naive("2026-05-04T15:30:00")
    assert dt is not None
    assert dt.tzinfo is None
    assert dt.hour == 15


def test_parse_iso_naive_handles_datetime_object_aware():
    """Un datetime aware est converti UTC puis stripé."""
    aware = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
    dt = parse_iso_naive(aware)
    assert dt is not None
    assert dt.tzinfo is None
    assert dt.hour == 12


def test_parse_iso_naive_handles_datetime_object_naive():
    """Un datetime naïf est renvoyé tel quel."""
    naive = datetime(2026, 5, 4, 12, 0)
    dt = parse_iso_naive(naive)
    assert dt == naive


def test_parse_iso_naive_invalid_returns_none():
    assert parse_iso_naive("not-a-date") is None
    assert parse_iso_naive("") is None
    assert parse_iso_naive(None) is None


# =============================================================================
# cutoff_from_hours
# =============================================================================


def test_cutoff_from_hours_returns_naive_datetime():
    """Le cutoff est un datetime naïf (cohérent DB)."""
    cutoff = cutoff_from_hours(24)
    assert cutoff.tzinfo is None


def test_cutoff_from_hours_in_the_past():
    """Le cutoff est forcément dans le passé."""
    from tik_core.utils.time import now_utc_naive

    now = now_utc_naive()
    cutoff = cutoff_from_hours(48)
    assert cutoff < now


# =============================================================================
# _build_record — conversion dict → HeadlineRecord
# =============================================================================


def test_build_record_valid_returns_headline_record():
    h = {
        "title": "BTC surges to ATH",
        "url": "https://example.com/article",
        "publisher": "Reuters",
        "sentiment": "bull",
        "fetched_at": "2026-05-04T22:00:00Z",
        "published_at": "2026-05-04T21:30:00Z",
    }
    record = _build_record("BTC", "google_news_rss", 0.70, h)
    assert record is not None
    assert isinstance(record, HeadlineRecord)
    assert record.entity_id == "BTC"
    assert record.source == "google_news_rss"
    assert record.title == "BTC surges to ATH"
    assert record.url == "https://example.com/article"
    assert record.publisher == "Reuters"
    assert record.sentiment == "bull"
    assert record.credibility == 0.70
    assert record.fetched_at is not None
    assert record.fetched_at.tzinfo is None  # strippé pour DB
    assert record.title_hash == compute_title_hash("BTC surges to ATH")


def test_build_record_skip_empty_title():
    h = {"title": "", "fetched_at": "2026-05-04T22:00:00Z"}
    assert _build_record("BTC", "x", 0.5, h) is None


def test_build_record_skip_whitespace_only_title():
    h = {"title": "   ", "fetched_at": "2026-05-04T22:00:00Z"}
    assert _build_record("BTC", "x", 0.5, h) is None


def test_build_record_default_publisher_unknown():
    h = {
        "title": "Some title",
        "fetched_at": "2026-05-04T22:00:00Z",
    }
    record = _build_record("BTC", "x", 0.5, h)
    assert record is not None
    assert record.publisher == "unknown"


def test_build_record_default_sentiment_neutral():
    h = {
        "title": "Some title",
        "fetched_at": "2026-05-04T22:00:00Z",
    }
    record = _build_record("BTC", "x", 0.5, h)
    assert record is not None
    assert record.sentiment == "neutral"


def test_build_record_published_at_optional():
    h = {
        "title": "Some title",
        "fetched_at": "2026-05-04T22:00:00Z",
        # Pas de published_at
    }
    record = _build_record("BTC", "x", 0.5, h)
    assert record is not None
    assert record.published_at is None


# =============================================================================
# persist_headlines — comportement avec mock session_maker
# =============================================================================


class _MockSession:
    """Mock minimal d'AsyncSession qui capture les records ajoutés."""

    def __init__(self, parent):
        self.parent = parent

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def add_all(self, records):
        self.parent.added_records.extend(records)

    async def commit(self):
        self.parent.commits += 1


class _MockSessionMaker:
    """Mock minimal d'async_sessionmaker."""

    def __init__(self, raise_on_commit: Exception | None = None):
        self.added_records: list = []
        self.commits = 0
        self._raise_on_commit = raise_on_commit

    def __call__(self):
        if self._raise_on_commit is not None:

            class _BrokenSession:
                async def __aenter__(self_inner):
                    return self_inner

                async def __aexit__(self_inner, *args):
                    return None

                def add_all(self_inner, records):
                    self.added_records.extend(records)

                async def commit(self_inner):
                    raise self._raise_on_commit

            return _BrokenSession()
        return _MockSession(self)


async def test_persist_headlines_returns_zero_when_session_maker_none():
    """Sans session_maker, on ne persiste rien (rétrocompat)."""
    headlines = [
        {"title": "Some", "fetched_at": "2026-05-04T22:00:00Z"},
    ]
    n = await persist_headlines(None, "BTC", "x", 0.5, headlines)
    assert n == 0


async def test_persist_headlines_returns_zero_when_empty_list():
    sm = _MockSessionMaker()
    n = await persist_headlines(sm, "BTC", "x", 0.5, [])
    assert n == 0
    assert sm.added_records == []


async def test_persist_headlines_inserts_valid_records():
    sm = _MockSessionMaker()
    headlines = [
        {
            "title": "A",
            "url": "u1",
            "publisher": "P1",
            "sentiment": "bull",
            "fetched_at": "2026-05-04T22:00:00Z",
        },
        {
            "title": "B",
            "url": "u2",
            "publisher": "P2",
            "sentiment": "bear",
            "fetched_at": "2026-05-04T22:00:00Z",
        },
    ]
    n = await persist_headlines(sm, "BTC", "google_news_rss", 0.70, headlines)
    assert n == 2
    assert len(sm.added_records) == 2
    assert sm.commits == 1
    assert sm.added_records[0].title == "A"
    assert sm.added_records[0].source == "google_news_rss"
    assert sm.added_records[1].sentiment == "bear"


async def test_persist_headlines_skips_invalid_records():
    """Records sans titre ou non-dict sont skippés."""
    sm = _MockSessionMaker()
    headlines = [
        {"title": "Valid", "fetched_at": "2026-05-04T22:00:00Z"},
        {"title": "", "fetched_at": "2026-05-04T22:00:00Z"},
        "not-a-dict",
        None,
        {"title": "   ", "fetched_at": "2026-05-04T22:00:00Z"},
        {"title": "Also valid", "fetched_at": "2026-05-04T22:00:00Z"},
    ]
    n = await persist_headlines(sm, "BTC", "x", 0.5, headlines)
    assert n == 2  # "Valid" et "Also valid" seulement
    titles = [r.title for r in sm.added_records]
    assert titles == ["Valid", "Also valid"]


async def test_persist_headlines_returns_zero_when_no_valid_records():
    """Tous skippés (pas d'INSERT lancé)."""
    sm = _MockSessionMaker()
    headlines = [{"title": ""}, "not-a-dict"]
    n = await persist_headlines(sm, "BTC", "x", 0.5, headlines)
    assert n == 0
    assert sm.commits == 0


async def test_persist_headlines_swallows_db_error():
    """Erreur DB en commit → log + retourne 0, ne raise pas."""
    sm = _MockSessionMaker(raise_on_commit=RuntimeError("postgres down"))
    headlines = [
        {"title": "Some", "fetched_at": "2026-05-04T22:00:00Z"},
    ]
    n = await persist_headlines(sm, "BTC", "x", 0.5, headlines)
    assert n == 0
