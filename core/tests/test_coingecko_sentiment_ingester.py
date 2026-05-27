"""Tests du helper pur du CoinGeckoSentimentIngester (SHADOW, ADR-021).

Aucune dépendance Redis/HTTP : on teste le parsing déterministe de la réponse
CoinGecko /coins/bitcoin.
"""

from tik_core.aggregator.coingecko_sentiment_ingester import _build_snapshot


class TestBuildSnapshot:
    def test_valid(self):
        snap = _build_snapshot(
            {
                "sentiment_votes_up_percentage": 64.2,
                "sentiment_votes_down_percentage": 35.8,
            },
            "2026-05-27T17:30:00+00:00",
        )
        assert snap is not None
        assert snap["source"] == "coingecko_sentiment"
        assert snap["up_pct"] == 64.2
        assert snap["down_pct"] == 35.8
        assert snap["fetched_at"] == "2026-05-27T17:30:00+00:00"

    def test_down_pct_missing_ok(self):
        # down_pct absent est toléré tant que up_pct est présent et valide.
        snap = _build_snapshot({"sentiment_votes_up_percentage": 50.0}, "t")
        assert snap is not None
        assert snap["up_pct"] == 50.0
        assert snap["down_pct"] is None

    def test_missing_up_pct(self):
        assert _build_snapshot({"sentiment_votes_down_percentage": 35.8}, "t") is None

    def test_non_numeric(self):
        assert _build_snapshot({"sentiment_votes_up_percentage": "nope"}, "t") is None

    def test_out_of_range_high(self):
        assert _build_snapshot({"sentiment_votes_up_percentage": 150.0}, "t") is None

    def test_out_of_range_negative(self):
        assert _build_snapshot({"sentiment_votes_up_percentage": -5.0}, "t") is None

    def test_not_a_dict(self):
        assert _build_snapshot(None, "t") is None
        assert _build_snapshot([], "t") is None

    def test_boundaries_valid(self):
        assert _build_snapshot({"sentiment_votes_up_percentage": 0.0}, "t") is not None
        assert _build_snapshot({"sentiment_votes_up_percentage": 100.0}, "t") is not None
