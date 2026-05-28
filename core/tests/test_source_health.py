"""Tests purs du moniteur de santé par source OSINT (étend M4).

Zéro IO : on teste l'extraction du timestamp, la classification ok/stale/missing,
l'agrégation et l'intégrité du registre SOURCE_SPECS.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from tik_core.metrics.source_health import (
    SOURCE_SPECS,
    SourceSpec,
    classify_source,
    compute_source_health,
    parse_fetched_at,
    summarize,
)

NOW = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)


def _payload(field: str, dt: datetime) -> str:
    return json.dumps({field: dt.isoformat()})


class TestParseFetchedAt:
    def test_fetched_at_aware(self):
        raw = _payload("fetched_at", NOW - timedelta(minutes=5))
        assert parse_fetched_at(raw, "fetched_at") == NOW - timedelta(minutes=5)

    def test_timestamp_field(self):
        raw = _payload("timestamp", NOW)
        assert parse_fetched_at(raw, "timestamp") == NOW

    def test_z_suffix_normalized(self):
        raw = json.dumps({"fetched_at": "2026-05-28T12:00:00Z"})
        assert parse_fetched_at(raw, "fetched_at") == NOW

    def test_naive_treated_as_utc(self):
        raw = json.dumps({"fetched_at": "2026-05-28T12:00:00"})
        got = parse_fetched_at(raw, "fetched_at")
        assert got == NOW and got.tzinfo is not None

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "not json",
            json.dumps([1, 2]),
            json.dumps("string"),
            json.dumps({"other": "x"}),
        ],
    )
    def test_unparseable_or_missing_field(self, raw):
        assert parse_fetched_at(raw, "fetched_at") is None

    def test_wrong_field_name(self):
        raw = _payload("timestamp", NOW)
        assert parse_fetched_at(raw, "fetched_at") is None

    def test_bad_date_value(self):
        raw = json.dumps({"fetched_at": "not-a-date"})
        assert parse_fetched_at(raw, "fetched_at") is None


SPEC = SourceSpec("x", "tik.x", "fetched_at", 600, True, "note")


class TestClassifySource:
    def test_ok_fresh(self):
        h = classify_source(SPEC, NOW - timedelta(seconds=300), NOW)
        assert h.status == "ok" and h.age_seconds == pytest.approx(300)

    def test_stale_old(self):
        h = classify_source(SPEC, NOW - timedelta(seconds=900), NOW)
        assert h.status == "stale" and h.age_seconds == pytest.approx(900)

    def test_missing_when_none(self):
        h = classify_source(SPEC, None, NOW)
        assert h.status == "missing" and h.age_seconds is None

    def test_boundary_at_threshold_is_ok(self):
        # âge == max_age → ok (stale seulement si STRICTEMENT supérieur)
        h = classify_source(SPEC, NOW - timedelta(seconds=600), NOW)
        assert h.status == "ok"

    def test_clock_skew_future_clamped(self):
        h = classify_source(SPEC, NOW + timedelta(seconds=120), NOW)
        assert h.status == "ok" and h.age_seconds == 0.0

    def test_carries_metadata(self):
        h = classify_source(SPEC, None, NOW)
        assert h.critical is True and h.note == "note" and h.redis_key == "tik.x"


class TestComputeSourceHealth:
    def test_mix(self):
        specs = (
            SourceSpec("fresh", "k.fresh", "fetched_at", 600, True, ""),
            SourceSpec("old", "k.old", "fetched_at", 600, False, ""),
            SourceSpec("gone", "k.gone", "fetched_at", 600, True, ""),
        )
        raw = {
            "k.fresh": _payload("fetched_at", NOW - timedelta(seconds=60)),
            "k.old": _payload("fetched_at", NOW - timedelta(seconds=5000)),
            # k.gone absent
        }
        out = compute_source_health(raw, NOW, specs)
        by = {h.name: h.status for h in out}
        assert by == {"fresh": "ok", "old": "stale", "gone": "missing"}


class TestSummarize:
    def test_counts_and_critical_down(self):
        specs = (
            SourceSpec("c_ok", "k1", "fetched_at", 600, True, ""),
            SourceSpec("c_down", "k2", "fetched_at", 600, True, ""),
            SourceSpec("nc_down", "k3", "fetched_at", 600, False, ""),
        )
        raw = {"k1": _payload("fetched_at", NOW)}  # k2, k3 missing
        s = summarize(compute_source_health(raw, NOW, specs))
        assert s["n_total"] == 3
        assert s["n_ok"] == 1
        assert s["n_missing"] == 2
        assert s["any_critical_down"] is True
        assert s["critical_down"] == ["c_down"]  # nc_down exclu (non critique)

    def test_all_ok_no_alert(self):
        specs = (SourceSpec("a", "k", "fetched_at", 600, True, ""),)
        raw = {"k": _payload("fetched_at", NOW)}
        s = summarize(compute_source_health(raw, NOW, specs))
        assert s["any_critical_down"] is False and s["critical_down"] == []


class TestSpecsIntegrity:
    def test_registry_sane(self):
        names = [s.name for s in SOURCE_SPECS]
        keys = [s.redis_key for s in SOURCE_SPECS]
        assert len(names) == len(set(names)), "noms de source dupliqués"
        assert len(keys) == len(set(keys)), "clés Redis dupliquées"
        for s in SOURCE_SPECS:
            assert s.ts_field in ("fetched_at", "timestamp")
            assert s.max_age_s >= 60
            assert s.redis_key.startswith("tik.")

    def test_reddit_present_and_noncritical(self):
        # Reddit doit être surveillé (Bug 11) mais non critique (mitigé)
        reddit = next((s for s in SOURCE_SPECS if s.name == "reddit_btc"), None)
        assert reddit is not None and reddit.critical is False

    def test_critical_set_expected(self):
        crit = {s.name for s in SOURCE_SPECS if s.critical}
        assert crit == {"fear_greed", "cryptocompare_news", "google_news_btc", "price_btc"}
