"""Tests des helpers purs du PolymarketIngester (SHADOW).

Aucune dépendance Redis/HTTP : on teste le parsing/agrégation déterministe.
"""

from tik_core.aggregator.polymarket_ingester import (
    _build_market_entry,
    _build_snapshot,
    _first_clob_token_id,
    _is_relevant_btc_event,
    _parse_outcome_prices,
    _parse_threshold_usd,
)


class TestParseOutcomePrices:
    def test_json_string(self):
        assert _parse_outcome_prices('["0.9995", "0.0005"]') == (0.9995, 0.0005)

    def test_list(self):
        assert _parse_outcome_prices(["0.044", "0.956"]) == (0.044, 0.956)

    def test_malformed_string(self):
        assert _parse_outcome_prices("pas du json") is None

    def test_too_short(self):
        assert _parse_outcome_prices(["0.5"]) is None

    def test_non_numeric(self):
        assert _parse_outcome_prices(["yes", "no"]) is None

    def test_none(self):
        assert _parse_outcome_prices(None) is None


class TestParseThresholdUsd:
    def test_comma_thousands(self):
        assert (
            _parse_threshold_usd("Will the price of Bitcoin be above $68,000 on May 24?") == 68000.0
        )

    def test_reach_full(self):
        assert _parse_threshold_usd("Will Bitcoin reach $115,000 in May?") == 115000.0

    def test_k_suffix(self):
        assert _parse_threshold_usd("When will Bitcoin hit $150k?") == 150000.0

    def test_m_suffix(self):
        assert _parse_threshold_usd("Will bitcoin hit $1m before GTA VI?") == 1_000_000.0

    def test_no_amount(self):
        assert _parse_threshold_usd("Bitcoin Up or Down today?") is None

    def test_empty(self):
        assert _parse_threshold_usd("") is None
        assert _parse_threshold_usd(None) is None


class TestFirstClobTokenId:
    def test_json_string(self):
        assert _first_clob_token_id('["123456", "789012"]') == "123456"

    def test_list(self):
        assert _first_clob_token_id(["abc", "def"]) == "abc"

    def test_empty(self):
        assert _first_clob_token_id("[]") is None
        assert _first_clob_token_id([]) is None

    def test_malformed(self):
        assert _first_clob_token_id("xxx") is None
        assert _first_clob_token_id(None) is None


class TestIsRelevantBtcEvent:
    def test_daily_above(self):
        assert _is_relevant_btc_event("Bitcoin above ___ on May 24?") is True

    def test_monthly_price(self):
        assert _is_relevant_btc_event("What price will Bitcoin hit in May?") is True

    def test_daily_price_on(self):
        assert _is_relevant_btc_event("Bitcoin price on May 23?") is True

    def test_up_or_down_excluded(self):
        assert _is_relevant_btc_event("Bitcoin Up or Down - May 23, 8:20AM-8:25AM ET") is False

    def test_novelty_excluded(self):
        # pas de "above...on", pas de "what price will bitcoin hit", pas de "bitcoin price on"
        assert _is_relevant_btc_event("Will bitcoin hit $1m before GTA VI?") is False

    def test_when_will_excluded(self):
        assert _is_relevant_btc_event("When will Bitcoin hit $150k?") is False

    def test_non_bitcoin(self):
        assert _is_relevant_btc_event("Kosice: Feldbausch vs Bailly") is False

    def test_none(self):
        assert _is_relevant_btc_event(None) is False


class TestBuildMarketEntry:
    def test_valid(self):
        m = {
            "question": "Will the price of Bitcoin be above $70,000 on May 24?",
            "outcomePrices": '["0.9995", "0.0005"]',
            "volume": "225971.1",
            "clobTokenIds": '["47774", "99999"]',
        }
        e = _build_market_entry(m)
        assert e["threshold_usd"] == 70000.0
        assert e["yes_prob"] == 0.9995
        assert e["no_prob"] == 0.0005
        assert e["volume"] == 225971.1
        assert e["clob_token_id"] == "47774"

    def test_bad_prices_returns_none(self):
        assert _build_market_entry({"question": "x", "outcomePrices": "nope"}) is None

    def test_volume_non_numeric_tolerated(self):
        m = {
            "question": "above $70,000 on May 24?",
            "outcomePrices": ["0.5", "0.5"],
            "volume": "n/a",
        }
        e = _build_market_entry(m)
        assert e is not None
        assert e["volume"] is None


class TestBuildSnapshot:
    def _ev(self, title, markets):
        return {"title": title, "slug": "s", "endDate": "2026-05-24T00:00:00Z", "markets": markets}

    def test_keeps_only_relevant_events(self):
        good = self._ev(
            "Bitcoin above ___ on May 24?",
            [
                {
                    "question": "above $70,000 on May 24?",
                    "outcomePrices": ["0.99", "0.01"],
                    "volume": "100",
                },
                {
                    "question": "above $80,000 on May 24?",
                    "outcomePrices": ["0.40", "0.60"],
                    "volume": "200",
                },
            ],
        )
        noise = self._ev(
            "Bitcoin Up or Down - May 24, 5:25AM ET",
            [{"question": "up?", "outcomePrices": ["0.5", "0.5"], "volume": "10"}],
        )
        sports = self._ev(
            "Feldbausch vs Bailly", [{"question": "?", "outcomePrices": ["0.5", "0.5"]}]
        )
        snap = _build_snapshot([good, noise, sports], "2026-05-24T03:00:00Z")
        assert snap["source"] == "polymarket"
        assert snap["mode"] == "shadow"
        assert snap["n_events"] == 1
        assert snap["events"][0]["title"] == "Bitcoin above ___ on May 24?"
        assert snap["events"][0]["n_markets"] == 2
        assert snap["events"][0]["total_volume"] == 300.0
        assert snap["total_volume"] == 300.0

    def test_relevant_event_without_parseable_markets_excluded(self):
        ev = self._ev("Bitcoin price on May 23?", [{"question": "?", "outcomePrices": "broken"}])
        snap = _build_snapshot([ev], "2026-05-24T03:00:00Z")
        assert snap["n_events"] == 0
        assert snap["total_volume"] == 0

    def test_empty(self):
        snap = _build_snapshot([], "2026-05-24T03:00:00Z")
        assert snap["n_events"] == 0
        assert snap["events"] == []
