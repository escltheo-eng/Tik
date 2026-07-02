"""Tests de l'endpoint d'ingestion micro (fusion macro+micro, ADR-030 Étape 2).

Vérifie qu'un signal externe 'micro' POSTé sur /api/v1/signals/ingest est :
- persisté en horizon='micro' (forcé serveur, pas choisi par l'appelant),
- marqué circuit_breaker_status='degraded' (shadow strict),
- entity_id normalisé en majuscules,
- doté d'une veracity conservatrice par défaut (0.70) si non fournie.

Skippe proprement sans Postgres de test (héritage auth_client → db_session →
db_engine, garde anti-prod du conftest). Redis est stubbé (publish no-op) pour
ne pas exiger de broker. L'entité BTC est seedée AVANT le POST : `signals` a une
FK vers `entities` (cf. test_publisher_timezone_db.py / CLAUDE.md Bug 9 contexte).
"""

import pytest

from tik_core.storage.models import Entity


class _FakeRedis:
    """Stub Redis minimal : publish no-op + aclose, pour ne pas exiger un broker."""

    async def publish(self, *args, **kwargs):  # noqa: ARG002
        return 0

    async def aclose(self):
        return None


async def _seed_btc_entity(db_session):
    """Garantit l'entité BTC (FK signals→entities) dans la transaction de test."""
    if await db_session.get(Entity, "BTC") is None:
        db_session.add(Entity(id="BTC", domain="crypto", namespace="binance"))
        await db_session.flush()


def _enable_micro(monkeypatch):
    """Active le kill-switch micro (défaut False, ADR-030) pour le test."""
    from tik_core.config import get_settings

    monkeypatch.setattr(get_settings(), "micro_ingest_enabled", True)


@pytest.mark.asyncio
async def test_ingest_micro_creates_degraded_micro_signal(
    auth_client, db_session, monkeypatch
):
    import tik_core.api.signals as signals_mod

    monkeypatch.setattr(signals_mod.aioredis, "from_url", lambda *a, **k: _FakeRedis())
    _enable_micro(monkeypatch)
    await _seed_btc_entity(db_session)

    payload = {
        "entity_id": "btc",  # minuscule → doit être normalisé en BTC
        "direction": "long",
        "confidence": 0.62,
        "hypothesis": "test micro shadow",
        "evidence": [{"source": "micro_lgb", "score": 0.7, "fact": "proba_up=0.62"}],
        "triggers": [{"type": "proba", "value": "0.62", "weight": 0.5}],
        "counter_scenarios": [
            {"name": "reversal", "probability": 0.4, "mitigation": "watch q10"}
        ],
    }
    resp = await auth_client.post("/api/v1/signals/ingest", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["horizon"] == "micro"
    assert data["direction"] == "long"
    assert data["circuit_breaker_status"] == "degraded"
    assert data["entity_id"] == "BTC"
    assert data["id"].startswith("TIK-MICRO-BTC-")
    assert data["veracity"] == pytest.approx(0.70)
    assert data["sources_count"] == 1


@pytest.mark.asyncio
async def test_ingest_micro_rejects_invalid_direction(auth_client, monkeypatch):
    import tik_core.api.signals as signals_mod

    monkeypatch.setattr(signals_mod.aioredis, "from_url", lambda *a, **k: _FakeRedis())

    resp = await auth_client.post(
        "/api/v1/signals/ingest",
        json={"direction": "sideways", "confidence": 0.5},
    )
    assert resp.status_code == 422  # le pattern long|short|neutral rejette


@pytest.mark.asyncio
async def test_ingest_micro_disabled_returns_503(auth_client, monkeypatch):
    """Kill-switch (ADR-030/ADR-034) : toggle off (défaut) → 503, rien n'entre."""
    import tik_core.api.signals as signals_mod

    monkeypatch.setattr(signals_mod.aioredis, "from_url", lambda *a, **k: _FakeRedis())
    # Ne PAS activer le toggle : défaut micro_ingest_enabled=False.
    from tik_core.config import get_settings

    monkeypatch.setattr(get_settings(), "micro_ingest_enabled", False)

    resp = await auth_client.post(
        "/api/v1/signals/ingest",
        json={"direction": "long", "confidence": 0.5},
    )
    assert resp.status_code == 503
    assert "TIK_MICRO_INGEST_ENABLED" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_micro_unknown_entity_returns_422(auth_client, monkeypatch):
    """Whitelist entités (défaut BTC) : entité inconnue → 422 propre, pas de 500 FK."""
    import tik_core.api.signals as signals_mod

    monkeypatch.setattr(signals_mod.aioredis, "from_url", lambda *a, **k: _FakeRedis())
    _enable_micro(monkeypatch)

    resp = await auth_client.post(
        "/api/v1/signals/ingest",
        json={"entity_id": "btcusdt", "direction": "long", "confidence": 0.5},
    )
    assert resp.status_code == 422
    assert "BTCUSDT" in resp.json()["detail"]
