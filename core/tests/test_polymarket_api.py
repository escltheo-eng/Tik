"""Tests des helpers purs de l'endpoint Polymarket (api/polymarket.py).

Pas de Redis/HTTP : on teste la normalisation snapshot (rétrocompat entity,
tri par volume, cap) et le snapshot vide.
"""

from tik_core.api.polymarket import _empty_snapshot, _finalize_payload


class TestEmptySnapshot:
    def test_fields(self):
        snap = _empty_snapshot("gold")
        assert snap.entity == "GOLD"
        assert snap.fetched_at is None
        assert snap.n_events == 0
        assert snap.events == []
        assert snap.mode == "shadow"


class TestFinalizePayload:
    def _payload(self, events, entity=None):
        p = {
            "source": "polymarket",
            "mode": "shadow",
            "fetched_at": "2026-05-28T00:00:00+00:00",
            "n_events": len(events),
            "total_volume": 0.0,
            "events": events,
        }
        if entity is not None:
            p["entity"] = entity
        return p

    def test_injects_entity_when_missing(self):
        # snapshot BTC pré-2026-05-28 sans champ entity
        snap = _finalize_payload(self._payload([]), "btc", limit=10)
        assert snap.entity == "BTC"

    def test_preserves_existing_entity(self):
        snap = _finalize_payload(self._payload([], entity="GOLD"), "btc", limit=10)
        assert snap.entity == "GOLD"

    def test_sorts_events_by_volume_desc(self):
        events = [
            {"title": "low", "total_volume": 100.0, "markets": []},
            {"title": "high", "total_volume": 900.0, "markets": []},
            {"title": "mid", "total_volume": 500.0, "markets": []},
        ]
        snap = _finalize_payload(self._payload(events, entity="GOLD"), "gold", limit=10)
        assert [e.title for e in snap.events] == ["high", "mid", "low"]

    def test_caps_to_limit(self):
        events = [{"title": f"e{i}", "total_volume": float(i), "markets": []} for i in range(20)]
        snap = _finalize_payload(self._payload(events, entity="BTC"), "btc", limit=3)
        assert len(snap.events) == 3
        # les 3 plus gros volumes (19, 18, 17)
        assert [e.title for e in snap.events] == ["e19", "e18", "e17"]

    def test_missing_total_volume_treated_as_zero(self):
        events = [
            {"title": "no_vol", "markets": []},
            {"title": "with_vol", "total_volume": 50.0, "markets": []},
        ]
        snap = _finalize_payload(self._payload(events, entity="GOLD"), "gold", limit=10)
        assert snap.events[0].title == "with_vol"
