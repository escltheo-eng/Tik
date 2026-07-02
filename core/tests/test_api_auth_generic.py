"""Garde-fou générique : TOUTE route REST hors PUBLIC_PATHS exige une clé API.

Audit 2026-07-02 : l'enforcement d'auth est opt-in par route (chaque endpoint
doit penser à déclarer `Depends(require_scope(...))`). Les 35 routes actuelles
sont protégées, mais rien n'empêchait une future route d'être silencieusement
publique. Ce test itère sur `app.routes` et vérifie qu'une requête SANS clé
reçoit 401 partout — il échoue dès qu'on ajoute une route non protégée.

Pas besoin de DB : la dépendance d'auth lève avant toute résolution de session.
"""

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient

from tik_core.main import PUBLIC_PATHS, app


def _collect_api_routes() -> list[tuple[str, APIRoute]]:
    """Aplati `app.routes` en (path complet, APIRoute).

    FastAPI récent n'aplatit plus les `include_router` : `app.routes` contient
    des wrappers `_IncludedRouter` portant le préfixe dans `include_context` et
    les APIRoute dans `original_router.routes`. On gère les deux formes pour
    rester robuste aux versions.
    """
    flat: list[tuple[str, APIRoute]] = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            flat.append((route.path, route))
            continue
        ctx = getattr(route, "include_context", None)
        inner = getattr(route, "original_router", None)
        if ctx is not None and inner is not None:
            prefix = getattr(ctx, "prefix", "") or ""
            flat.extend(
                (prefix + r.path, r) for r in inner.routes if isinstance(r, APIRoute)
            )
    return flat


def _rest_routes() -> list[tuple[str, str]]:
    """(méthode, path concret) pour chaque route REST /api/v1 non publique."""
    cases = []
    for path, route in _collect_api_routes():
        if not path.startswith("/api/v1"):
            continue
        if path in PUBLIC_PATHS:
            continue
        # Path params remplacés par une valeur bidon : l'auth lève avant
        # la validation du paramètre, le 401 doit gagner.
        concrete = path.replace("{signal_id}", "TIK-TEST").replace("{entity_id}", "BTC")
        # Tout paramètre restant (nouvelle route future) : valeur générique.
        while "{" in concrete:
            start = concrete.index("{")
            end = concrete.index("}", start)
            concrete = concrete[:start] + "TEST" + concrete[end + 1 :]
        for method in route.methods - {"HEAD", "OPTIONS"}:
            cases.append((method, concrete))
    return sorted(cases)


@pytest.mark.asyncio
async def test_every_non_public_route_requires_api_key(api_client: AsyncClient):
    # Certains endpoints déclarent `Depends(get_session)` AVANT l'auth : sans
    # lifespan, get_session lèverait « DB engine not initialized » (500) avant
    # que l'auth ne réponde 401. On le remplace par un stub inoffensif — les
    # endpoints ne s'exécutent jamais (l'auth refuse), la session n'est pas
    # utilisée. On n'override PAS l'auth : c'est elle qu'on teste.
    from tik_core.storage.database import get_session

    async def _stub_session():
        yield None

    app.dependency_overrides[get_session] = _stub_session
    try:
        await _assert_all_routes_reject(api_client)
    finally:
        app.dependency_overrides.pop(get_session, None)


async def _assert_all_routes_reject(api_client: AsyncClient) -> None:
    cases = _rest_routes()
    # Sanity : si ce nombre s'effondre, le test ne protège plus rien.
    assert len(cases) >= 35, f"seulement {len(cases)} routes détectées"

    offenders = []
    for method, path in cases:
        resp = await api_client.request(method, path, json={})
        if resp.status_code != 401:
            offenders.append((method, path, resp.status_code))
    assert not offenders, (
        "Routes accessibles sans clé API (attendu 401) — toute nouvelle route "
        f"doit déclarer Depends(require_scope(...)) : {offenders}"
    )


@pytest.mark.asyncio
async def test_health_is_public(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/health")
    assert resp.status_code == 200
