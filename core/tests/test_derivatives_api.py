"""Tests des helpers purs de l'endpoint dérivés (api/derivatives.py, ADR-023).

Pas de Redis/HTTP : snapshot vide + construction du schéma depuis un payload réel.
"""

from tik_core.api.derivatives import _empty_snapshot
from tik_core.storage.schemas import DerivativesSnapshotOut

FULL_PAYLOAD = {
    "source": "binance_derivatives",
    "entity": "BTC",
    "funding_rate": 3.958e-05,
    "mark_price": 67044.94,
    "next_funding_time": 1780502400000,
    "open_interest_btc": 107593.242,
    "open_interest_usd": 7213583026.57,
    "long_short_ratio_global": 2.2123,
    "long_account_global": 0.6887,
    "short_account_global": 0.3113,
    "long_short_ratio_top": 2.2279,
    "long_account_top": 0.6902,
    "short_account_top": 0.3098,
    "fetched_at": "2026-06-03T11:59:59+00:00",
}


class TestEmptySnapshot:
    def test_fields(self):
        snap = _empty_snapshot("btc")
        assert snap.entity == "BTC"
        assert snap.fetched_at is None
        assert snap.funding_rate is None
        assert snap.mode == "shadow"
        assert snap.source == "binance_derivatives"


class TestConstructFromPayload:
    def test_full(self):
        snap = DerivativesSnapshotOut(**FULL_PAYLOAD)
        assert snap.entity == "BTC"
        assert snap.mode == "shadow"  # absent du payload → défaut
        assert snap.funding_rate == 3.958e-05
        assert snap.open_interest_usd == 7213583026.57
        assert snap.long_account_global == 0.6887
        assert snap.long_short_ratio_top == 2.2279
        assert snap.fetched_at == "2026-06-03T11:59:59+00:00"

    def test_partial(self):
        # Snapshot où seuls funding + mark_price ont réussi (autres None).
        snap = DerivativesSnapshotOut(
            entity="BTC", funding_rate=1e-4, mark_price=67000.0, fetched_at="t"
        )
        assert snap.funding_rate == 1e-4
        assert snap.open_interest_usd is None
        assert snap.long_account_global is None
