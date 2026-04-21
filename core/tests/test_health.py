"""Test du endpoint /health — ne nécessite pas DB/Redis."""

import pytest


@pytest.mark.asyncio
async def test_health_ok(api_client):
    """Le endpoint /health répond 200 avec la version."""
    r = await api_client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "env" in data
