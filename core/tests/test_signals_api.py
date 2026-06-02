"""Tests HTTP bout-en-bout des endpoints /signals (comble un gap — 2026-06-01).

Avant ce fichier, `api/signals.py` n'avait **aucun** test HTTP : les signaux
étaient lus en prod (dashboard) mais jamais via un test couvrant route +
session DB + auth ensemble. Un bug dans `get_signal` / `search_signals`
(mauvais code HTTP, filtre cassé, sérialisation) passait sous le radar de la CI.

On couvre ici : `/latest` (ordre + limite), `/{id}` (200 et 404), recherche
filtrée (entity / horizon / direction / veracity / fenêtre temporelle), et le
refus de scope (403). Pré-requis : Postgres `tik_test` (fixture `db_session`).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth.dependencies import get_auth_context
from tik_core.auth.provider import AuthContext
from tik_core.main import app
from tik_core.storage.database import get_session
from tik_core.storage.models import Entity, Signal
from tik_core.utils.time import now_utc_naive

PREFIX = "/api/v1/signals"


@pytest_asyncio.fixture
async def seeded_signals(db_session: AsyncSession) -> list[Signal]:
    """Entité BTC + 3 signaux variés (flush only → rollback en teardown).

    Aucune écriture n'est committée : la fixture `db_session` rollback en
    teardown, donc rien ne pollue `tik_test`.
    """
    if await db_session.get(Entity, "BTC") is None:
        db_session.add(Entity(id="BTC", domain="crypto", namespace="binance"))
        await db_session.flush()

    now = now_utc_naive()
    signals = [
        Signal(
            id="TIK-TEST-SIG-A",
            timestamp=now - timedelta(hours=1),
            entity_id="BTC",
            horizon="swing",
            direction="short",
            confidence=0.6,
            veracity=0.90,
            hypothesis="hypo-a",
            evidence=[{"source": "fear_greed", "score": 1.0, "fact": "f"}],
        ),
        Signal(
            id="TIK-TEST-SIG-B",
            timestamp=now - timedelta(hours=2),
            entity_id="BTC",
            horizon="flash",
            direction="long",
            confidence=0.2,
            veracity=0.70,
            hypothesis="hypo-b",
            evidence=[],
        ),
        Signal(
            id="TIK-TEST-SIG-C",
            timestamp=now - timedelta(hours=50),  # hors fenêtre 24h par défaut
            entity_id="BTC",
            horizon="swing",
            direction="neutral",
            confidence=0.0,
            veracity=0.85,
            hypothesis="hypo-c",
            evidence=[],
        ),
    ]
    for s in signals:
        db_session.add(s)
    await db_session.flush()
    return signals


@pytest.mark.asyncio
async def test_latest_returns_signals_in_reverse_chronological_order(
    auth_client: AsyncClient, seeded_signals: list[Signal]
) -> None:
    resp = await auth_client.get(f"{PREFIX}/latest", params={"entity": "BTC"})
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    # Les 3 signaux BTC seedés sont présents…
    for sid in ("TIK-TEST-SIG-A", "TIK-TEST-SIG-B", "TIK-TEST-SIG-C"):
        assert sid in ids
    # …et l'ordre est antéchronologique (A 1h < B 2h < C 50h d'âge).
    assert ids.index("TIK-TEST-SIG-A") < ids.index("TIK-TEST-SIG-B")
    assert ids.index("TIK-TEST-SIG-B") < ids.index("TIK-TEST-SIG-C")


@pytest.mark.asyncio
async def test_latest_respects_limit(
    auth_client: AsyncClient, seeded_signals: list[Signal]
) -> None:
    resp = await auth_client.get(f"{PREFIX}/latest", params={"entity": "BTC", "limit": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    # Le plus récent = SIG-A.
    assert body[0]["id"] == "TIK-TEST-SIG-A"


@pytest.mark.asyncio
async def test_get_signal_by_id_returns_full_payload(
    auth_client: AsyncClient, seeded_signals: list[Signal]
) -> None:
    resp = await auth_client.get(f"{PREFIX}/TIK-TEST-SIG-A")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "TIK-TEST-SIG-A"
    assert body["direction"] == "short"
    assert body["confidence"] == 0.6
    assert body["veracity"] == 0.90
    assert body["entity_id"] == "BTC"
    # Sérialisation timezone-aware (ADR-013) : suffixe Z.
    assert body["timestamp"].endswith("Z")


@pytest.mark.asyncio
async def test_get_signal_unknown_id_returns_404(
    auth_client: AsyncClient, seeded_signals: list[Signal]
) -> None:
    resp = await auth_client.get(f"{PREFIX}/TIK-DOES-NOT-EXIST")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Signal not found"


@pytest.mark.asyncio
async def test_search_excludes_signals_outside_time_window(
    auth_client: AsyncClient, seeded_signals: list[Signal]
) -> None:
    # since_hours=24 par défaut → SIG-C (50h) doit être exclu.
    resp = await auth_client.get(PREFIX, params={"entity": "BTC"})
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    assert "TIK-TEST-SIG-A" in ids
    assert "TIK-TEST-SIG-B" in ids
    assert "TIK-TEST-SIG-C" not in ids


@pytest.mark.asyncio
async def test_search_filters_by_direction(
    auth_client: AsyncClient, seeded_signals: list[Signal]
) -> None:
    resp = await auth_client.get(PREFIX, params={"entity": "BTC", "direction": "short"})
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    assert ids == ["TIK-TEST-SIG-A"]  # seul SIG-A est short dans la fenêtre 24h


@pytest.mark.asyncio
async def test_search_filters_by_min_veracity(
    auth_client: AsyncClient, seeded_signals: list[Signal]
) -> None:
    resp = await auth_client.get(PREFIX, params={"entity": "BTC", "min_veracity": 0.88})
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    assert "TIK-TEST-SIG-A" in ids  # veracity 0.90 ≥ 0.88
    assert "TIK-TEST-SIG-B" not in ids  # veracity 0.70 < 0.88


@pytest.mark.asyncio
async def test_search_rejects_invalid_horizon_pattern(
    auth_client: AsyncClient, seeded_signals: list[Signal]
) -> None:
    # `horizon` a un pattern ^(flash|swing|macro)$ → 422 sinon.
    resp = await auth_client.get(PREFIX, params={"horizon": "scalp"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_missing_scope_is_forbidden(db_session: AsyncSession) -> None:
    """Un contexte sans le scope `read:signals` doit recevoir 403.

    On n'utilise pas `auth_client` (qui injecte `admin`) : on câble nous-mêmes
    un contexte aux scopes vides pour exercer la branche `require_scope`.
    """

    async def _override_session():
        yield db_session

    def _override_no_scope() -> AuthContext:
        return AuthContext(client_id="test-client", scopes=[])

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_auth_context] = _override_no_scope
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/latest")
        assert resp.status_code == 403
        assert "read:signals" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_auth_context, None)
