"""Tests HTTP de POST /feedback (comble un gap + capte un bug latent — 2026-06-01).

`api/feedback.py` n'avait **aucun** test HTTP. En écrivant ces tests on a
découvert un **bug latent** : l'endpoint construisait un `Feedback` sans
`signal_timestamp`, colonne `NOT NULL` sans défaut (cf. models.py) → l'INSERT
levait `NotNullViolation`. L'endpoint n'avait jamais été exercé en prod (aucun
bot client câblé, SDK gelé ADR-022), donc le bug dormait. Fix : reprendre
`signal_timestamp` du signal chargé. Ces tests verrouillent le comportement.

Pré-requis : Postgres `tik_test` (fixture `db_session`).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.storage.models import Entity, Feedback, Signal
from tik_core.utils.time import now_utc_naive

PREFIX = "/api/v1/feedback"


@pytest_asyncio.fixture
async def seeded_signal(db_session: AsyncSession) -> Signal:
    """Entité BTC + 1 signal référençable par le feedback (flush only)."""
    if await db_session.get(Entity, "BTC") is None:
        db_session.add(Entity(id="BTC", domain="crypto", namespace="binance"))
        await db_session.flush()

    signal = Signal(
        id="TIK-TEST-FB-SIG",
        timestamp=now_utc_naive(),
        entity_id="BTC",
        horizon="swing",
        direction="short",
        confidence=0.5,
        veracity=0.88,
        hypothesis="hypo",
        evidence=[],
    )
    db_session.add(signal)
    await db_session.flush()
    return signal


@pytest.mark.asyncio
async def test_submit_feedback_happy_path_returns_201(
    auth_client: AsyncClient, seeded_signal: Signal
) -> None:
    resp = await auth_client.post(
        PREFIX,
        json={
            "signal_id": "TIK-TEST-FB-SIG",
            "trade_id": "trade-1",
            "outcome": "win",
            "pnl_pct": 1.23,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["signal_id"] == "TIK-TEST-FB-SIG"
    assert body["outcome"] == "win"
    assert body["client_id"] == "test-client"  # vient du contexte auth
    assert "id" in body
    assert body["received_at"].endswith("Z")


@pytest.mark.asyncio
async def test_submit_feedback_populates_signal_timestamp(
    auth_client: AsyncClient, seeded_signal: Signal, db_session: AsyncSession
) -> None:
    """Garde-fou anti-régression du bug : `signal_timestamp` doit être renseigné.

    Si quelqu'un retire `signal_timestamp=signal.timestamp` de l'endpoint,
    l'INSERT relèvera NotNullViolation et ce test (comme le happy path) cassera.
    """
    resp = await auth_client.post(PREFIX, json={"signal_id": "TIK-TEST-FB-SIG", "outcome": "loss"})
    assert resp.status_code == 201, resp.text

    row = (
        await db_session.execute(select(Feedback).where(Feedback.signal_id == "TIK-TEST-FB-SIG"))
    ).scalar_one()
    assert row.signal_timestamp is not None
    assert row.signal_timestamp == seeded_signal.timestamp


@pytest.mark.asyncio
async def test_submit_feedback_unknown_signal_returns_404(
    auth_client: AsyncClient, seeded_signal: Signal
) -> None:
    resp = await auth_client.post(PREFIX, json={"signal_id": "TIK-NOPE", "outcome": "win"})
    assert resp.status_code == 404
    assert "TIK-NOPE" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_submit_feedback_invalid_outcome_returns_422(
    auth_client: AsyncClient, seeded_signal: Signal
) -> None:
    # `outcome` a un pattern ^(win|loss|breakeven|not_taken)$.
    resp = await auth_client.post(
        PREFIX, json={"signal_id": "TIK-TEST-FB-SIG", "outcome": "banana"}
    )
    assert resp.status_code == 422
