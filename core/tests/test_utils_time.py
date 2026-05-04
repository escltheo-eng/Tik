"""Tests des helpers timezone-aware (cf. ADR-013).

Couverture : `now_utc`, `now_utc_naive`, `iso_utc` (sérialisation ISO-Z).
"""

from datetime import datetime, timezone

import pytest

from tik_core.utils.time import iso_utc, now_utc, now_utc_naive


# =====================================================================
# now_utc
# =====================================================================

def test_now_utc_returns_aware_datetime():
    dt = now_utc()
    assert dt.tzinfo is not None
    assert dt.tzinfo.utcoffset(dt).total_seconds() == 0


def test_now_utc_close_to_real_now():
    dt = now_utc()
    real = datetime.now(timezone.utc)
    delta = abs((real - dt).total_seconds())
    assert delta < 1.0


# =====================================================================
# now_utc_naive
# =====================================================================

def test_now_utc_naive_returns_naive_datetime():
    dt = now_utc_naive()
    assert dt.tzinfo is None


def test_now_utc_naive_semantically_utc():
    """La valeur naïve doit être proche de l'UTC réel (en valeur)."""
    naive = now_utc_naive()
    aware = datetime.now(timezone.utc).replace(tzinfo=None)
    delta = abs((aware - naive).total_seconds())
    assert delta < 1.0


# =====================================================================
# iso_utc — sérialisation
# =====================================================================

def test_iso_utc_none_returns_none():
    assert iso_utc(None) is None


def test_iso_utc_naive_assumes_utc_and_appends_z():
    naive = datetime(2026, 5, 4, 11, 32, 14, 554000)
    out = iso_utc(naive)
    assert out is not None
    assert out.endswith("Z")
    assert out == "2026-05-04T11:32:14.554000Z"


def test_iso_utc_aware_utc_uses_z():
    aware = datetime(2026, 5, 4, 11, 32, 14, tzinfo=timezone.utc)
    out = iso_utc(aware)
    assert out == "2026-05-04T11:32:14Z"


def test_iso_utc_aware_offset_converts_to_utc():
    """Un datetime aware avec offset non-UTC doit être converti et marqué Z."""
    from datetime import timedelta as td
    paris = timezone(td(hours=2))
    aware = datetime(2026, 5, 4, 13, 32, 14, tzinfo=paris)  # = 11:32:14 UTC
    out = iso_utc(aware)
    assert out == "2026-05-04T11:32:14Z"


def test_iso_utc_no_double_suffix_on_existing_z():
    """Si la chaîne ISO finit déjà par +00:00, on remplace par Z, pas Z+00:00."""
    aware = datetime(2026, 5, 4, 0, 0, 0, tzinfo=timezone.utc)
    out = iso_utc(aware)
    assert out is not None
    assert "+00:00" not in out
    assert out.count("Z") == 1
