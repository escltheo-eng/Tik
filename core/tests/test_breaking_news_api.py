"""Tests API des endpoints breaking-news (ADR-027) — ferme le trou de
vérification HTTP+auth+sérialisation (le dry-run ne couvrait que la logique).

Vérifie : route enregistrée, auth satisfaite (scope admin), réponse 200, type
liste, et structure des items si présents. Lecture réelle de Redis (les items
viennent du flux live) → assertions structurelles, pas sur des valeurs précises.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_breaking_news_endpoint_ok(auth_client: AsyncClient):
    r = await auth_client.get("/api/v1/metrics/breaking_news?limit=5")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) <= 5
    for it in data:
        assert "title" in it
        assert "category" in it
        # `title_fr` doit exister dans le schéma (peut être null).
        assert "title_fr" in it


@pytest.mark.asyncio
async def test_breaking_news_limit_validation(auth_client: AsyncClient):
    # limit > borne max (40) → 422 (validation FastAPI).
    r = await auth_client.get("/api/v1/metrics/breaking_news?limit=999")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_breaking_reactions_endpoint_ok(auth_client: AsyncClient):
    r = await auth_client.get("/api/v1/metrics/breaking_reactions?limit=5")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    for rx in data:
        assert "pct" in rx
        assert "horizon_h" in rx
        assert "category" in rx
