"""Tests unitaires du pipeline golden dataset (Paquet 4 Session 4).

Couvre les fonctions pures des 4 scripts :
- collect_golden : _make_id, _load_existing_ids, quotas_for, pick_new
- predict_golden : _verdict_from_counts, _load_existing_predictions
- backtest_golden : _parse_horizon, _parse_dt, _compute_deltas_for_item
- measure_calibration : _verdict_correct_vs_market, _accuracy,
  _confusion_matrix, _hit_rate_vs_market, _baseline_random/constant,
  _build_combined, _section_distribution, _section_concordance, _render_markdown

Aucune dépendance Redis / DB / HTTP : on teste la logique sans infrastructure.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tik_core.scripts.collect_golden import (
    CollectedItem,
    _load_existing_ids,
    _make_id,
    pick_new,
    quotas_for,
)
from tik_core.scripts.predict_golden import (
    _load_existing_predictions,
    _verdict_from_counts,
)
from tik_core.scripts.backtest_golden import (
    _compute_deltas_for_item,
    _parse_dt,
    _parse_horizon,
)
from tik_core.scripts.measure_calibration import (
    _accuracy,
    _baseline_constant_hit_rate,
    _baseline_random_hit_rate,
    _build_combined,
    _confusion_matrix,
    _hit_rate_vs_market,
    _index_by_id,
    _render_markdown,
    _section_concordance,
    _section_distribution,
    _verdict_correct_vs_market,
)


# =============================================================================
# collect_golden — fonctions pures
# =============================================================================


class TestMakeId:
    def test_stable_for_same_input(self):
        a = _make_id("btc", "google_news", "Bitcoin surges")
        b = _make_id("btc", "google_news", "Bitcoin surges")
        assert a == b

    def test_different_for_different_text(self):
        a = _make_id("btc", "google_news", "Bitcoin surges")
        b = _make_id("btc", "google_news", "Bitcoin crashes")
        assert a != b

    def test_different_for_different_source(self):
        a = _make_id("btc", "google_news", "Bitcoin surges")
        b = _make_id("btc", "reddit", "Bitcoin surges")
        assert a != b

    def test_different_for_different_asset(self):
        a = _make_id("btc", "google_news", "Bitcoin surges")
        b = _make_id("gold", "google_news", "Bitcoin surges")
        assert a != b

    def test_returns_16_hex_chars(self):
        h = _make_id("btc", "google_news", "test")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)


class TestLoadExistingIds:
    def test_returns_empty_set_if_file_missing(self, tmp_path: Path):
        ids = _load_existing_ids(tmp_path / "nope.jsonl")
        assert ids == set()

    def test_loads_ids_from_file(self, tmp_path: Path):
        path = tmp_path / "items.jsonl"
        path.write_text(
            json.dumps({"id": "abc", "text": "x"}) + "\n"
            + json.dumps({"id": "def", "text": "y"}) + "\n",
            encoding="utf-8",
        )
        assert _load_existing_ids(path) == {"abc", "def"}

    def test_skips_invalid_json_lines(self, tmp_path: Path):
        path = tmp_path / "items.jsonl"
        path.write_text(
            json.dumps({"id": "abc"}) + "\n"
            + "not json\n"
            + json.dumps({"id": "def"}) + "\n",
            encoding="utf-8",
        )
        assert _load_existing_ids(path) == {"abc", "def"}

    def test_skips_empty_lines(self, tmp_path: Path):
        path = tmp_path / "items.jsonl"
        path.write_text(
            json.dumps({"id": "abc"}) + "\n\n\n",
            encoding="utf-8",
        )
        assert _load_existing_ids(path) == {"abc"}

    def test_skips_records_without_id(self, tmp_path: Path):
        path = tmp_path / "items.jsonl"
        path.write_text(
            json.dumps({"id": "abc"}) + "\n"
            + json.dumps({"foo": "bar"}) + "\n",
            encoding="utf-8",
        )
        assert _load_existing_ids(path) == {"abc"}


class TestQuotasFor:
    def test_btc_50_splits_evenly(self):
        q = quotas_for("btc", 50)
        assert q == {"google_news": 17, "cryptocompare": 17, "reddit": 16}
        assert sum(q.values()) == 50

    def test_btc_30_splits(self):
        q = quotas_for("btc", 30)
        assert sum(q.values()) == 30

    def test_btc_3_splits_evenly(self):
        q = quotas_for("btc", 3)
        assert q == {"google_news": 1, "cryptocompare": 1, "reddit": 1}

    def test_gold_uses_only_google_news(self):
        q = quotas_for("gold", 50)
        assert q == {"google_news": 50}

    def test_unknown_asset_raises(self):
        with pytest.raises(ValueError):
            quotas_for("eth", 50)


class TestPickNew:
    def _items(self, ids: list[str]) -> list[CollectedItem]:
        return [
            CollectedItem(
                id=i,
                asset="btc",
                source="google_news",
                text=f"text {i}",
                metadata={},
                fetched_at="2026-05-01T00:00:00+00:00",
                fetch_price=100.0,
            )
            for i in ids
        ]

    def test_returns_first_n_when_no_existing(self):
        items = self._items(["a", "b", "c", "d"])
        out = pick_new(items, quota=2, existing_ids=set())
        assert [i.id for i in out] == ["a", "b"]

    def test_skips_existing_ids(self):
        items = self._items(["a", "b", "c", "d"])
        out = pick_new(items, quota=2, existing_ids={"a", "c"})
        assert [i.id for i in out] == ["b", "d"]

    def test_skips_intra_batch_duplicates(self):
        items = self._items(["a", "a", "b"])  # dup id "a"
        out = pick_new(items, quota=3, existing_ids=set())
        assert [i.id for i in out] == ["a", "b"]

    def test_returns_empty_when_quota_zero(self):
        items = self._items(["a", "b"])
        out = pick_new(items, quota=0, existing_ids=set())
        assert out == []

    def test_preserves_order(self):
        items = self._items(["c", "b", "a"])
        out = pick_new(items, quota=3, existing_ids=set())
        assert [i.id for i in out] == ["c", "b", "a"]


# =============================================================================
# predict_golden — fonctions pures
# =============================================================================


class TestVerdictFromCounts:
    def test_bull_when_n_bull_higher(self):
        assert _verdict_from_counts(2, 1) == "bull"

    def test_bear_when_n_bear_higher(self):
        assert _verdict_from_counts(0, 1) == "bear"

    def test_neutral_when_equal(self):
        assert _verdict_from_counts(1, 1) == "neutral"

    def test_neutral_when_both_zero(self):
        assert _verdict_from_counts(0, 0) == "neutral"


class TestLoadExistingPredictions:
    def test_returns_empty_if_file_missing(self, tmp_path: Path):
        ids = _load_existing_predictions(tmp_path / "nope.jsonl")
        assert ids == set()

    def test_loads_ids(self, tmp_path: Path):
        path = tmp_path / "preds.jsonl"
        path.write_text(
            json.dumps({"id": "abc"}) + "\n"
            + json.dumps({"id": "def"}) + "\n",
            encoding="utf-8",
        )
        assert _load_existing_predictions(path) == {"abc", "def"}


# =============================================================================
# backtest_golden — fonctions pures
# =============================================================================


class TestParseHorizon:
    @pytest.mark.parametrize(
        "token,expected",
        [
            ("1h", 3600),
            ("6h", 21600),
            ("24h", 86400),
            ("1d", 86400),
            ("5d", 5 * 86400),
            ("7d", 7 * 86400),
        ],
    )
    def test_valid_horizons(self, token, expected):
        assert _parse_horizon(token) == expected

    def test_case_insensitive(self):
        assert _parse_horizon("1H") == 3600

    def test_invalid_unit_raises(self):
        with pytest.raises(ValueError):
            _parse_horizon("1y")

    def test_no_unit_raises(self):
        with pytest.raises(ValueError):
            _parse_horizon("5")


class TestParseDt:
    def test_iso_with_tz(self):
        dt = _parse_dt("2026-05-01T18:00:00+00:00")
        assert dt.tzinfo is not None
        assert dt.year == 2026 and dt.month == 5 and dt.day == 1

    def test_iso_without_tz_assumes_utc(self):
        dt = _parse_dt("2026-05-01T18:00:00")
        assert dt.tzinfo == timezone.utc


class TestComputeDeltasForItem:
    def _make_item(self, fetched_at: str, fetch_price: float = 100.0) -> dict:
        return {
            "id": "abc",
            "asset": "btc",
            "fetched_at": fetched_at,
            "fetch_price": fetch_price,
        }

    def _make_history(self, points: list[tuple[datetime, float]]) -> list[tuple[int, float]]:
        return [(int(dt.timestamp() * 1000), p) for dt, p in points]

    def test_horizon_in_future_marked_unavailable(self):
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        # Item collecté à 11:30, horizon 1h serait 12:30 → après now
        item = self._make_item("2026-05-01T11:30:00+00:00")
        history = self._make_history([])
        out = _compute_deltas_for_item(item, history, ["1h"], now)
        assert out["deltas"]["1h"]["available"] is False
        assert out["deltas"]["1h"]["reason"] == "horizon_in_future"

    def test_no_fetch_price_marked_unavailable(self):
        now = datetime(2026, 5, 5, tzinfo=timezone.utc)
        item = self._make_item("2026-05-01T00:00:00+00:00", fetch_price=None)  # type: ignore
        history = self._make_history(
            [(datetime(2026, 5, 1, 1, 0, tzinfo=timezone.utc), 200.0)]
        )
        out = _compute_deltas_for_item(item, history, ["1h"], now)
        assert out["deltas"]["1h"]["available"] is False
        assert out["deltas"]["1h"]["reason"] == "no_fetch_price"

    def test_delta_computed_correctly(self):
        now = datetime(2026, 5, 5, tzinfo=timezone.utc)
        item = self._make_item("2026-05-01T00:00:00+00:00", fetch_price=100.0)
        # 1h plus tard, prix à 101 → delta +1.0 %
        history = self._make_history(
            [(datetime(2026, 5, 1, 1, 0, tzinfo=timezone.utc), 101.0)]
        )
        out = _compute_deltas_for_item(item, history, ["1h"], now)
        assert out["deltas"]["1h"]["available"] is True
        assert out["deltas"]["1h"]["price"] == 101.0
        assert out["deltas"]["1h"]["delta_pct"] == 1.0


# =============================================================================
# measure_calibration — fonctions pures
# =============================================================================


class TestVerdictCorrectVsMarket:
    def test_bull_correct_when_market_up(self):
        assert _verdict_correct_vs_market("bull", 1.0, threshold=0.5) is True

    def test_bull_wrong_when_market_flat(self):
        assert _verdict_correct_vs_market("bull", 0.3, threshold=0.5) is False

    def test_bull_wrong_when_market_down(self):
        assert _verdict_correct_vs_market("bull", -1.0, threshold=0.5) is False

    def test_bear_correct_when_market_down(self):
        assert _verdict_correct_vs_market("bear", -1.0, threshold=0.5) is True

    def test_bear_wrong_when_market_up(self):
        assert _verdict_correct_vs_market("bear", 1.0, threshold=0.5) is False

    def test_neutral_correct_when_market_flat(self):
        assert _verdict_correct_vs_market("neutral", 0.2, threshold=0.5) is True

    def test_neutral_wrong_when_market_moves(self):
        assert _verdict_correct_vs_market("neutral", 1.0, threshold=0.5) is False
        assert _verdict_correct_vs_market("neutral", -1.0, threshold=0.5) is False

    def test_unknown_verdict_returns_false(self):
        assert _verdict_correct_vs_market("strong_bull", 5.0, threshold=0.5) is False


class TestAccuracy:
    def test_perfect_accuracy(self):
        records = [
            {"a": "bull", "b": "bull"},
            {"a": "bear", "b": "bear"},
            {"a": "neutral", "b": "neutral"},
        ]
        assert _accuracy(records, "a", "b") == 1.0

    def test_zero_accuracy(self):
        records = [
            {"a": "bull", "b": "bear"},
            {"a": "bear", "b": "bull"},
        ]
        assert _accuracy(records, "a", "b") == 0.0

    def test_partial(self):
        records = [
            {"a": "bull", "b": "bull"},
            {"a": "bull", "b": "bear"},
        ]
        assert _accuracy(records, "a", "b") == 0.5

    def test_skips_none_values(self):
        records = [
            {"a": None, "b": "bull"},
            {"a": "bull", "b": "bull"},
        ]
        assert _accuracy(records, "a", "b") == 1.0

    def test_returns_none_if_no_eligible(self):
        records = [{"a": None, "b": "bull"}]
        assert _accuracy(records, "a", "b") is None


class TestConfusionMatrix:
    def test_diagonal_when_perfect(self):
        records = [{"a": "bull", "b": "bull"}, {"a": "bear", "b": "bear"}]
        m = _confusion_matrix(records, "a", "b")
        assert m["bull"]["bull"] == 1
        assert m["bear"]["bear"] == 1
        assert m["bull"]["bear"] == 0

    def test_off_diagonal_when_disagreement(self):
        records = [{"a": "bull", "b": "bear"}]
        m = _confusion_matrix(records, "a", "b")
        assert m["bull"]["bear"] == 1


class TestHitRateVsMarket:
    def _record(self, verdict: str, delta: float) -> dict:
        return {
            "v": verdict,
            "deltas": {"1h": {"available": True, "delta_pct": delta}},
        }

    def test_all_correct(self):
        records = [
            self._record("bull", 1.0),
            self._record("bear", -1.0),
            self._record("neutral", 0.1),
        ]
        out = _hit_rate_vs_market(records, "v", "1h", 0.5)
        assert out["n"] == 3
        assert out["n_correct"] == 3
        assert out["hit_rate"] == 1.0

    def test_skips_unavailable(self):
        records = [
            self._record("bull", 1.0),
            {"v": "bull", "deltas": {"1h": {"available": False}}},
        ]
        out = _hit_rate_vs_market(records, "v", "1h", 0.5)
        assert out["n"] == 1


class TestBaselines:
    def _record(self, delta: float) -> dict:
        return {"deltas": {"1h": {"available": True, "delta_pct": delta}}}

    def test_random_returns_around_third(self):
        # 99 records bull (delta +1) → random pick 1/3 bull, 1/3 bear, 1/3 neutral
        # bull correct, bear wrong, neutral wrong → ~33% hit rate
        records = [self._record(1.0)] * 99
        out = _baseline_random_hit_rate(records, "1h", 0.5)
        assert 0.20 < out["hit_rate"] < 0.45

    def test_constant_bull_correct_when_all_up(self):
        records = [self._record(1.0), self._record(1.5)]
        out = _baseline_constant_hit_rate(records, "bull", "1h", 0.5)
        assert out["hit_rate"] == 1.0


class TestBuildCombined:
    def test_joins_4_sources(self):
        items = [
            {"id": "a", "asset": "btc", "source": "google_news", "text": "x"},
            {"id": "b", "asset": "gold", "source": "google_news", "text": "y"},
        ]
        annotations = {"a": {"verdict": "bull"}}
        predictions = {
            "a": {"predictions": {
                "ollama": {"verdict": "bull"},
                "keywords": {"verdict": "neutral"},
            }}
        }
        prices = {"b": {"deltas": {"1h": {"available": True, "delta_pct": 0.5}}}}

        records = _build_combined(items, annotations, predictions, prices)
        assert len(records) == 2
        a, b = records
        assert a["id"] == "a"
        assert a["human"] == "bull"
        assert a["ollama"] == "bull"
        assert a["keywords"] == "neutral"
        assert a["deltas"] == {}
        assert b["id"] == "b"
        assert b["human"] is None
        assert b["ollama"] is None
        assert b["deltas"] == {"1h": {"available": True, "delta_pct": 0.5}}


class TestSectionDistribution:
    def test_counts_and_pct(self):
        records = [
            {"human": "bull", "ollama": "bull", "keywords": None},
            {"human": "bear", "ollama": "bull", "keywords": None},
            {"human": None, "ollama": None, "keywords": None},
        ]
        out = _section_distribution(records)
        assert out["human"]["counts"]["bull"] == 1
        assert out["human"]["counts"]["bear"] == 1
        assert out["human"]["counts"]["n/a"] == 1
        assert out["ollama"]["counts"]["bull"] == 2
        assert out["keywords"]["counts"]["n/a"] == 3


class TestSectionConcordance:
    def test_perfect_match(self):
        records = [
            {"human": "bull", "ollama": "bull", "keywords": "bull"},
            {"human": "bear", "ollama": "bear", "keywords": "bear"},
        ]
        out = _section_concordance(records)
        assert out["human_vs_ollama"]["accuracy"] == 1.0
        assert out["human_vs_keywords"]["accuracy"] == 1.0


class TestRenderMarkdown:
    def test_renders_minimal_report_without_crash(self):
        report = {
            "meta": {
                "generated_at": "2026-05-02T00:00:00+00:00",
                "n_total": 0,
                "n_btc": 0,
                "n_gold": 0,
                "n_annotated": 0,
                "n_ollama": 0,
                "horizons": ["1h"],
                "threshold": 0.5,
            },
            "distribution": _section_distribution([]),
            "concordance": _section_concordance([]),
            "market_calibration": {"1h": {
                "human": None, "ollama": None, "keywords": None,
                "baselines": {
                    "random": None, "always_bull": None,
                    "always_bear": None, "always_neutral": None,
                },
            }},
            "per_source": {},
        }
        md = _render_markdown(report)
        assert "Rapport de calibration" in md
        assert "## 1. Distribution des verdicts" in md
        assert "## 2. Concordance" in md
        assert "## 3. Calibration vs marché réel" in md


class TestIndexById:
    def test_index_dedupes_on_id(self):
        records = [{"id": "a", "x": 1}, {"id": "a", "x": 2}, {"id": "b", "x": 3}]
        idx = _index_by_id(records)
        assert idx["a"]["x"] == 2  # le dernier gagne
        assert idx["b"]["x"] == 3

    def test_skips_records_without_id(self):
        records = [{"id": "a", "x": 1}, {"x": 2}]
        idx = _index_by_id(records)
        assert idx == {"a": {"id": "a", "x": 1}}
