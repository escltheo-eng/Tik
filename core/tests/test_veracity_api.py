"""Tests HTTP des endpoints /veracity (comble un gap — 2026-06-01).

`api/veracity.py` n'avait **aucun** test HTTP. On couvre la moyenne pondérée
par tier (`/global`), le cas « aucune source » (statut degraded), le listing
(`/sources`, actif vs inactif) et le détail (`/sources/{id}`, 200 et 404).

Déterminisme sur base partagée : chaque test vide d'abord la table `sources`
**dans la transaction** (rollback en teardown via `db_session`), donc aucune
source pré-existante de `tik_test` ne fausse les assertions, et rien n'est
committé. Pré-requis : Postgres `tik_test`.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.storage.models import Source

PREFIX = "/api/v1/veracity"


def _src(sid: str, tier: int, veracity: float, active: bool = True) -> Source:
    return Source(
        id=sid,
        name=sid.replace("_", " ").title(),
        category="sentiment",
        base_veracity=veracity,
        current_veracity=veracity,
        tier=tier,
        active=active,
    )


@pytest_asyncio.fixture
async def reset_sources(db_session: AsyncSession):
    """Vide `sources` en transaction avant le test (rollback en teardown)."""
    await db_session.execute(delete(Source))
    await db_session.flush()
    return db_session


@pytest.mark.asyncio
async def test_global_veracity_weighted_by_tier(
    auth_client: AsyncClient, reset_sources: AsyncSession
) -> None:
    # tier 1 → poids 5, tier 4 → poids 2 ; une source inactive est ignorée.
    reset_sources.add(_src("binance_klines", tier=1, veracity=0.9))
    reset_sources.add(_src("reddit_btc", tier=4, veracity=0.6))
    reset_sources.add(_src("dead_src", tier=3, veracity=0.1, active=False))
    await reset_sources.flush()

    resp = await auth_client.get(f"{PREFIX}/global")
    assert resp.status_code == 200
    body = resp.json()
    # (0.9*5 + 0.6*2) / (5+2) = 5.7/7 = 0.8143
    assert body["global_veracity"] == round(5.7 / 7, 4)
    assert body["sources_count_active"] == 2  # l'inactive est exclue
    assert body["status"] == "healthy"  # ≥ 0.7
    assert body["last_computed"].endswith("Z")


@pytest.mark.asyncio
async def test_global_veracity_no_sources_is_degraded(
    auth_client: AsyncClient, reset_sources: AsyncSession
) -> None:
    resp = await auth_client.get(f"{PREFIX}/global")
    assert resp.status_code == 200
    body = resp.json()
    assert body["global_veracity"] == 0.0
    assert body["sources_count_active"] == 0
    assert body["status"] == "degraded"


@pytest.mark.asyncio
async def test_global_veracity_collapse_below_0_4(
    auth_client: AsyncClient, reset_sources: AsyncSession
) -> None:
    reset_sources.add(_src("compromised", tier=1, veracity=0.2))
    await reset_sources.flush()
    resp = await auth_client.get(f"{PREFIX}/global")
    body = resp.json()
    assert body["global_veracity"] == 0.2
    assert body["status"] == "collapse"  # < 0.4


@pytest.mark.asyncio
async def test_list_sources_active_only_by_default(
    auth_client: AsyncClient, reset_sources: AsyncSession
) -> None:
    reset_sources.add(_src("active_src", tier=2, veracity=0.8))
    reset_sources.add(_src("inactive_src", tier=2, veracity=0.8, active=False))
    await reset_sources.flush()

    resp = await auth_client.get(f"{PREFIX}/sources")
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    assert "active_src" in ids
    assert "inactive_src" not in ids


@pytest.mark.asyncio
async def test_list_sources_includes_inactive_when_requested(
    auth_client: AsyncClient, reset_sources: AsyncSession
) -> None:
    reset_sources.add(_src("active_src", tier=2, veracity=0.8))
    reset_sources.add(_src("inactive_src", tier=2, veracity=0.8, active=False))
    await reset_sources.flush()

    resp = await auth_client.get(f"{PREFIX}/sources", params={"active_only": "false"})
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    assert "active_src" in ids
    assert "inactive_src" in ids


@pytest.mark.asyncio
async def test_get_source_by_id(auth_client: AsyncClient, reset_sources: AsyncSession) -> None:
    reset_sources.add(_src("binance_klines", tier=1, veracity=0.9))
    await reset_sources.flush()

    resp = await auth_client.get(f"{PREFIX}/sources/binance_klines")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "binance_klines"
    assert body["tier"] == 1
    assert body["current_veracity"] == 0.9


@pytest.mark.asyncio
async def test_get_source_unknown_returns_404(
    auth_client: AsyncClient, reset_sources: AsyncSession
) -> None:
    resp = await auth_client.get(f"{PREFIX}/sources/ghost_source")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Source not found"
