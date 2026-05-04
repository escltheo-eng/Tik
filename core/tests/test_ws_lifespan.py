"""Test d'intégration : startup complet de l'app FastAPI + connexion WebSocket.

Ce fichier prévient les régressions du type "import statique de _session_maker
dans un module FastAPI", documenté dans CLAUDE.md section 9 bug 7.

Pourquoi un test dédié plutôt que de réutiliser les fixtures existantes :

- La fixture `api_client` du conftest utilise `httpx.ASGITransport` sans
  LifespanManager : le lifespan FastAPI n'est jamais déclenché pendant
  les tests classiques. Donc `init_engine()` n'est pas appelé, et le
  bug d'import statique ne se manifeste pas.

- La fixture `db_engine` crée son propre engine via `create_async_engine`
  et NE TOUCHE PAS au global `database._session_maker`. Le global reste
  à `None` même quand un test tape la DB.

- Aucun test existant ne fait de vraie connexion WebSocket : le bug 7
  pouvait régresser sans que la CI ne le voie.

La parade : démarrer l'app via `TestClient` dans un `with` (qui exécute
le lifespan startup), puis faire une connexion WS authentifiée. Ce test
plante explicitement si quelqu'un réintroduit `from tik_core.storage.database
import _session_maker` au lieu de l'accès dynamique `database._session_maker`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tik_core.auth.api_key import generate_key
from tik_core.config import get_settings
from tik_core.main import app
from tik_core.storage import database
from tik_core.storage.models import ApiKey, Base


def _make_sync_engine() -> Engine:
    """Engine SQLAlchemy sync (psycopg2) vers la DB du settings courant.

    On ne réutilise pas la fixture `db_engine` du conftest : elle est async
    et drop_all en teardown, ce qui plante sur une DB Postgres avec des
    hypertables Timescale (cas du dev local). On construit notre propre
    engine sync, idempotent, sans drop final.
    """
    settings = get_settings()
    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    return create_engine(sync_url)


@pytest.fixture(scope="module", autouse=True)
def _ensure_tables_exist() -> None:
    """Crée les tables si elles n'existent pas (idempotent).

    Couvre les deux modes :
    - CI : Postgres démarre vide → on crée les tables.
    - Local : tables déjà créées par Alembic → no-op.

    Pas de drop en teardown : on laisse la DB telle quelle pour ne pas
    casser le scheduler/ingesters qui tournent en parallèle en local.
    """
    sync_engine = _make_sync_engine()
    try:
        Base.metadata.create_all(sync_engine)
    finally:
        sync_engine.dispose()


@pytest.fixture
def ws_api_key() -> Iterator[str]:
    """Insère une clé API valide en DB pour les tests WS et la nettoie après.

    Engine sync (psycopg2) parce que TestClient est sync — on évite la
    gymnastique sync↔async pour ce test ciblé.
    """
    sync_engine = _make_sync_engine()
    raw, hashed, suffix = generate_key()

    with Session(sync_engine) as session:
        session.add(
            ApiKey(
                name="ws-lifespan-test",
                client_id=f"ws_test_{suffix}",
                key_hash=hashed,
                key_suffix=suffix,
                scopes=["read:signals"],
                active=True,
            )
        )
        session.commit()

    try:
        yield raw
    finally:
        with Session(sync_engine) as session:
            session.execute(delete(ApiKey).where(ApiKey.key_hash == hashed))
            session.commit()
        sync_engine.dispose()


def test_session_maker_is_initialized_after_lifespan() -> None:
    """Garde-fou : à l'entrée du `with TestClient`, le lifespan a tourné
    et `database._session_maker` n'est plus None.

    Si le lifespan n'est pas appelé (mauvais TestClient, mauvaise config),
    ce test plante AVANT le test WS — utile pour isoler la cause.
    """
    with TestClient(app):
        assert database._session_maker is not None, (
            "Lifespan FastAPI n'a pas initialisé database._session_maker. "
            "Vérifie que main.lifespan() appelle bien init_engine()."
        )


def test_ws_connection_with_full_app_lifespan(ws_api_key: str) -> None:
    """Test principal : app complète + connexion WS authentifiée.

    REGRESSION GUARD CLAUDE.md section 9 bug 7. Si quelqu'un réintroduit
    `from tik_core.storage.database import _session_maker` dans
    `core/src/tik_core/api/ws.py`, ce test échoue avec un close 1011
    (WebSocketDisconnect) : `ws.py` voit `_session_maker = None` parce
    qu'il a gelé la référence avant que le lifespan ne soit appelé.
    """
    with TestClient(app) as client:
        url = f"/api/v1/ws/signals?api_key={ws_api_key}"
        with client.websocket_connect(url) as ws:
            assert ws is not None


def test_ws_rejects_invalid_key() -> None:
    """Test négatif : clé invalide → close 1008 (policy violation).

    Sert à isoler la cause d'échec du test principal :
    - Si ce test passe ET le test principal échoue → bug 7 (close 1011).
    - Si ce test échoue aussi → autre problème (DB down, etc.).
    """
    with TestClient(app) as client:
        url = "/api/v1/ws/signals?api_key=tik_definitely_not_a_real_key"
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(url):
                pass
        assert exc_info.value.code == 1008
