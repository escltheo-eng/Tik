"""Tests du TTL adaptatif du cache track record (Paquet 38).

Logique pure (pas de Redis/HTTP/DB). Verrouille le fix du bug "favori flash
tout sablier figé 6h" : un résultat contenant des lignes en_attente doit avoir
un TTL court (expiré peu après la prochaine échéance), un résultat entièrement
résolu garde le TTL long de 6h.
"""

from datetime import datetime, timedelta

from tik_core.api.metrics import (
    TRACK_RECORD_CACHE_TTL_SECONDS,
    TRACK_RECORD_MIN_TTL_SECONDS,
    _track_record_cache_ttl,
)

NOW = datetime(2026, 5, 26, 12, 0, 0)


def _row(badge: str, target: datetime) -> dict:
    return {"badge": badge, "target_iso": target.strftime("%Y-%m-%dT%H:%M:%SZ")}


def test_fully_resolved_uses_long_ttl():
    rows = [
        _row("correct", NOW - timedelta(hours=1)),
        _row("raté", NOW - timedelta(minutes=30)),
    ]
    assert _track_record_cache_ttl(rows, NOW) == TRACK_RECORD_CACHE_TTL_SECONDS


def test_donnees_manquantes_counts_as_resolved():
    # données_manquantes n'est pas en_attente → résultat considéré résolu.
    rows = [
        _row("correct", NOW - timedelta(hours=2)),
        _row("données_manquantes", NOW - timedelta(hours=1)),
    ]
    assert _track_record_cache_ttl(rows, NOW) == TRACK_RECORD_CACHE_TTL_SECONDS


def test_fresh_flash_all_pending_is_not_cached_6h():
    """Le cœur du bug : un flash frais (4 sabliers) ne doit pas être figé 6h."""
    rows = [
        _row("en_attente", NOW + timedelta(minutes=15)),
        _row("en_attente", NOW + timedelta(minutes=30)),
        _row("en_attente", NOW + timedelta(minutes=45)),
        _row("en_attente", NOW + timedelta(minutes=60)),
    ]
    ttl = _track_record_cache_ttl(rows, NOW)
    # Soonest = +15min → 900s + 30s buffer.
    assert ttl == 15 * 60 + 30
    assert ttl < TRACK_RECORD_CACHE_TTL_SECONDS


def test_uses_soonest_pending_target():
    # Première ligne résolue, les suivantes en attente → on prend la + proche.
    rows = [
        _row("correct", NOW - timedelta(minutes=5)),
        _row("en_attente", NOW + timedelta(minutes=10)),
        _row("en_attente", NOW + timedelta(minutes=40)),
    ]
    assert _track_record_cache_ttl(rows, NOW) == 10 * 60 + 30


def test_imminent_target_clamped_to_min():
    rows = [_row("en_attente", NOW + timedelta(seconds=5))]
    # 5 + 30 = 35 < plancher 60 → clampé à 60.
    assert _track_record_cache_ttl(rows, NOW) == TRACK_RECORD_MIN_TTL_SECONDS


def test_far_pending_target_clamped_to_max():
    # Cas swing : ligne 5j encore en attente → ne pas dépasser 6h.
    rows = [
        _row("correct", NOW - timedelta(hours=1)),
        _row("en_attente", NOW + timedelta(days=5)),
    ]
    assert _track_record_cache_ttl(rows, NOW) == TRACK_RECORD_CACHE_TTL_SECONDS


def test_past_pending_target_clamped_to_min():
    # Défensif : horizon techniquement dépassé mais encore marqué en_attente
    # (ex. bougie pas encore fetchable). seconds_until négatif → plancher.
    rows = [_row("en_attente", NOW - timedelta(minutes=5))]
    assert _track_record_cache_ttl(rows, NOW) == TRACK_RECORD_MIN_TTL_SECONDS
