"""Tests du carnet de trades manuels (Levier B 2026-06-03).

Deux couches :
  - fonctions pures du repo (calcul résultat %, alignement, stats) — sans DB ;
  - HTTP bout-en-bout via `auth_client` (POST/GET/PATCH/DELETE) sur `tik_test`.

Le cœur testé est l'invariant de mesure : `tik_alignment` (with/against/none)
et la décomposition `by_alignment` du bilan — c'est ce qui rend l'apport de
Tik mesurable. Pré-requis HTTP : Postgres `tik_test` (fixture `db_session`).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tik_core.storage.manual_trades_repo import (
    compute_alignment,
    compute_result_pct,
    compute_stats,
)
from tik_core.storage.models import ManualTrade

PREFIX = "/api/v1/trades"


# --------------------------------------------------------------------------
# Fonctions pures (pas de DB)
# --------------------------------------------------------------------------


def test_compute_result_pct_long_win() -> None:
    # long 100 → 110 = +10%
    assert compute_result_pct("long", 100.0, 110.0) == pytest.approx(10.0)


def test_compute_result_pct_long_loss() -> None:
    assert compute_result_pct("long", 100.0, 95.0) == pytest.approx(-5.0)


def test_compute_result_pct_short_win() -> None:
    # short 100 → 90 = +10% (le prix baisse, le short gagne)
    assert compute_result_pct("short", 100.0, 90.0) == pytest.approx(10.0)


def test_compute_result_pct_short_loss() -> None:
    assert compute_result_pct("short", 100.0, 108.0) == pytest.approx(-8.0)


@pytest.mark.parametrize(
    "direction,tik,expected",
    [
        ("long", "long", "with"),
        ("short", "short", "with"),
        ("long", "short", "against"),
        ("short", "long", "against"),
        ("long", "neutral", "none"),
        ("short", None, "none"),
        ("long", "", "none"),
    ],
)
def test_compute_alignment(direction: str, tik: str | None, expected: str) -> None:
    assert compute_alignment(direction, tik) == expected


def _trade(alignment: str | None, result_pct: float, status: str = "closed") -> ManualTrade:
    """Fabrique un ManualTrade en mémoire (sans session) pour tester compute_stats."""
    return ManualTrade(
        id=f"t-{alignment}-{result_pct}",
        entity_id="BTC",
        direction="short",
        entry_time=None,
        entry_price=100.0,
        size_lots=0.1,
        status=status,
        result_pct=result_pct,
        tik_alignment=alignment,
    )


def test_compute_stats_groups_by_alignment() -> None:
    trades = [
        _trade("with", 2.0),
        _trade("with", -1.0),
        _trade("against", -3.0),
        _trade("none", 0.5),
        _trade("with", 1.0, status="open"),  # open → ignoré dans les métriques
    ]
    stats = compute_stats(trades)
    assert stats["n_total"] == 5
    assert stats["n_open"] == 1
    assert stats["n_closed"] == 4
    # global : 4 clôturés, 2 gagnants (>0) → 50%
    assert stats["win_rate"] == pytest.approx(0.5)
    with_grp = stats["by_alignment"]["with"]
    assert with_grp["n"] == 2
    assert with_grp["win_rate"] == pytest.approx(0.5)
    assert with_grp["avg_result_pct"] == pytest.approx(0.5)  # (2 + -1)/2
    assert stats["by_alignment"]["against"]["n"] == 1
    assert stats["by_alignment"]["none"]["n"] == 1


def test_compute_stats_empty_groups_are_safe() -> None:
    stats = compute_stats([])
    assert stats["n_closed"] == 0
    assert stats["win_rate"] is None
    assert stats["by_alignment"]["with"]["n"] == 0
    assert stats["by_alignment"]["with"]["win_rate"] is None


# --------------------------------------------------------------------------
# HTTP bout-en-bout
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_trade_happy_path(auth_client: AsyncClient) -> None:
    resp = await auth_client.post(
        PREFIX,
        json={
            "entity_id": "BTC",
            "direction": "short",
            "entry_price": 64250.0,
            "size_lots": 0.1,
            "note": "RSI bearish",
            "tik_signal_id": "TIK-SWING-BTC-X",
            "tik_direction": "short",
            "tik_veracity": 0.86,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "open"
    assert body["tik_alignment"] == "with"  # short + Tik short
    assert body["result_pct"] is None
    assert body["entry_time"].endswith("Z")
    assert "id" in body


@pytest.mark.asyncio
async def test_open_trade_against_and_none_alignment(auth_client: AsyncClient) -> None:
    # long contre Tik short → against
    r1 = await auth_client.post(
        PREFIX,
        json={
            "entity_id": "BTC", "direction": "long", "entry_price": 100.0,
            "size_lots": 0.1, "tik_direction": "short",
        },
    )
    assert r1.json()["tik_alignment"] == "against"
    # sans contexte Tik → none
    r2 = await auth_client.post(
        PREFIX,
        json={"entity_id": "BTC", "direction": "long", "entry_price": 100.0, "size_lots": 0.1},
    )
    assert r2.json()["tik_alignment"] == "none"


@pytest.mark.asyncio
async def test_open_trade_invalid_payload_returns_422(auth_client: AsyncClient) -> None:
    # entity hors whitelist
    r1 = await auth_client.post(
        PREFIX,
        json={"entity_id": "ETH", "direction": "long", "entry_price": 1.0, "size_lots": 0.1},
    )
    assert r1.status_code == 422
    # prix négatif
    r2 = await auth_client.post(
        PREFIX,
        json={"entity_id": "BTC", "direction": "long", "entry_price": -5.0, "size_lots": 0.1},
    )
    assert r2.status_code == 422
    # direction invalide
    r3 = await auth_client.post(
        PREFIX,
        json={"entity_id": "BTC", "direction": "sideways", "entry_price": 1.0, "size_lots": 0.1},
    )
    assert r3.status_code == 422


@pytest.mark.asyncio
async def test_list_and_close_and_stats_flow(auth_client: AsyncClient) -> None:
    # 1) ouvrir un short BTC aligné avec Tik
    opened = await auth_client.post(
        PREFIX,
        json={
            "entity_id": "BTC", "direction": "short", "entry_price": 100.0,
            "size_lots": 0.2, "tik_direction": "short",
        },
    )
    trade_id = opened.json()["id"]

    # 2) il apparaît dans la liste, statut open
    listing = await auth_client.get(PREFIX)
    assert listing.status_code == 200
    ids = [t["id"] for t in listing.json()]
    assert trade_id in ids

    # 3) clôturer à 90 → short gagnant +10%
    closed = await auth_client.patch(
        f"{PREFIX}/{trade_id}/close", json={"exit_price": 90.0}
    )
    assert closed.status_code == 200, closed.text
    cbody = closed.json()
    assert cbody["status"] == "closed"
    assert cbody["result_pct"] == pytest.approx(10.0)
    assert cbody["exit_time"].endswith("Z")

    # 4) le bilan reflète le trade clôturé dans le groupe "with"
    stats = await auth_client.get(f"{PREFIX}/stats")
    assert stats.status_code == 200
    sbody = stats.json()
    assert sbody["n_closed"] >= 1
    assert sbody["by_alignment"]["with"]["n"] >= 1


@pytest.mark.asyncio
async def test_close_unknown_returns_404(auth_client: AsyncClient) -> None:
    resp = await auth_client.patch(f"{PREFIX}/nope-id/close", json={"exit_price": 1.0})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_trade_flow(auth_client: AsyncClient) -> None:
    opened = await auth_client.post(
        PREFIX,
        json={"entity_id": "BTC", "direction": "long", "entry_price": 100.0, "size_lots": 0.1},
    )
    trade_id = opened.json()["id"]
    deleted = await auth_client.delete(f"{PREFIX}/{trade_id}")
    assert deleted.status_code == 204
    # re-supprimer → 404
    again = await auth_client.delete(f"{PREFIX}/{trade_id}")
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_filter_by_status(auth_client: AsyncClient) -> None:
    o = await auth_client.post(
        PREFIX,
        json={"entity_id": "BTC", "direction": "short", "entry_price": 100.0, "size_lots": 0.1},
    )
    tid = o.json()["id"]
    await auth_client.patch(f"{PREFIX}/{tid}/close", json={"exit_price": 95.0})
    closed_only = await auth_client.get(PREFIX, params={"status": "closed"})
    assert all(t["status"] == "closed" for t in closed_only.json())
    assert tid in [t["id"] for t in closed_only.json()]
