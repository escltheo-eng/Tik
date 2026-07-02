"""Tests HTTP des routes /entities (CRUD) — trou de couverture audit 2026-07-02.

Aucune route entities n'avait de test HTTP : create 201, doublon 409 (les deux
chemins : check d'existence ET IntegrityError TOCTOU), list, get 404,
soft-delete 204. Pattern `auth_client` + `db_session` (rollback en teardown,
rien n'est persisté).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

PREFIX = "/api/v1/entities"


def _payload(entity_id: str) -> dict:
    return {
        "id": entity_id,
        "domain": "trading",
        "namespace": "test",
        "metadata": {"source": "test_entities_api"},
    }


def _unique_id() -> str:
    return f"E2E-{uuid.uuid4().hex[:8].upper()}"


@pytest.mark.asyncio
async def test_create_entity_returns_201_with_payload(auth_client: AsyncClient):
    entity_id = _unique_id()
    resp = await auth_client.post(PREFIX, json=_payload(entity_id))
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == entity_id
    assert body["domain"] == "trading"
    assert body["active"] is True


@pytest.mark.asyncio
async def test_create_duplicate_returns_409(auth_client: AsyncClient):
    entity_id = _unique_id()
    first = await auth_client.post(PREFIX, json=_payload(entity_id))
    assert first.status_code == 201
    dup = await auth_client.post(PREFIX, json=_payload(entity_id))
    assert dup.status_code == 409
    assert entity_id in dup.json()["detail"]


@pytest.mark.asyncio
async def test_create_race_integrity_error_returns_409_not_500(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """TOCTOU (audit 2026-07-02) : deux créations concurrentes passent toutes
    les deux le check d'existence, la contrainte PK tranche au flush. On simule
    la course en faisant lever IntegrityError par le flush : la réponse doit
    être un 409 explicite, pas un 500 opaque."""

    async def _racing_flush(*args, **kwargs):
        raise IntegrityError("INSERT INTO entities", {}, Exception("duplicate key"))

    monkeypatch.setattr(db_session, "flush", _racing_flush)
    resp = await auth_client.post(PREFIX, json=_payload(_unique_id()))
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_entities_filters_inactive_by_default(auth_client: AsyncClient):
    entity_id = _unique_id()
    await auth_client.post(PREFIX, json=_payload(entity_id))
    resp = await auth_client.delete(f"{PREFIX}/{entity_id}")
    assert resp.status_code == 204

    default_list = await auth_client.get(PREFIX)
    assert default_list.status_code == 200
    assert entity_id not in [e["id"] for e in default_list.json()]

    full_list = await auth_client.get(PREFIX, params={"active_only": "false"})
    assert entity_id in [e["id"] for e in full_list.json()]


@pytest.mark.asyncio
async def test_get_entity_by_id_and_404(auth_client: AsyncClient):
    entity_id = _unique_id()
    await auth_client.post(PREFIX, json=_payload(entity_id))

    found = await auth_client.get(f"{PREFIX}/{entity_id}")
    assert found.status_code == 200
    assert found.json()["id"] == entity_id

    missing = await auth_client.get(f"{PREFIX}/E2E-DOES-NOT-EXIST")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_soft_delete_is_soft_and_404_on_unknown(auth_client: AsyncClient):
    entity_id = _unique_id()
    await auth_client.post(PREFIX, json=_payload(entity_id))

    resp = await auth_client.delete(f"{PREFIX}/{entity_id}")
    assert resp.status_code == 204

    # Soft delete : l'entity existe toujours, seulement inactive.
    still_there = await auth_client.get(f"{PREFIX}/{entity_id}")
    assert still_there.status_code == 200
    assert still_there.json()["active"] is False

    unknown = await auth_client.delete(f"{PREFIX}/E2E-DOES-NOT-EXIST")
    assert unknown.status_code == 404
