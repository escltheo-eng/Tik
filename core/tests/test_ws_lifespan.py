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


# ============================================================================
# REGRESSION GUARDS Bug 10 — WebSocket coroutine zombie au close brutal client
# ============================================================================
# CLAUDE.md section 9 Bug 10 : audit santé runtime 2026-05-17 a découvert que
# le `except Exception` autour de `websocket.send_json` dans `ws.py` n'avait
# PAS de `break`. Conséquence : à chaque nouveau signal publié sur Redis
# après la déconnexion brutale d'un client, la coroutine handler retentait
# `send_json` sur une WS fermée → spam de warnings + connexions Redis pubsub
# qui s'accumulent + saturation event loop → API `/health` timeout.
#
# Le bug a tourné **3h sans détection** (tik-core "unhealthy") parce que :
# - Aucun test ne fermait brutalement une WS puis publiait sur Redis
# - Le pattern Expo Go iPhone (changement WiFi, swipe down app, etc.)
#   reproduit exactement ce scenario en production
#
# Fix : sépare `try parse JSON (continue)` de `try send_json (break)`. Les
# tests ci-dessous valident le comportement attendu.


def test_ws_module_source_has_break_after_client_gone() -> None:
    """SMOKE TEST source code — vérifie que le `break` est présent dans le
    bloc `except` autour de `websocket.send_json` (Bug 10 régression guard).

    Test rapide et fiable (pas de network, pas de Redis). Plante immédiatement
    si quelqu'un retire le `break` lors d'un refactor sans relire CLAUDE.md
    section 9 Bug 10.
    """
    from pathlib import Path

    ws_src = Path(__file__).parent.parent / "src" / "tik_core" / "api" / "ws.py"
    source = ws_src.read_text(encoding="utf-8")

    # Le log doit être présent (signature du fix)
    assert 'ws.client_gone' in source, (
        "Bug 10 régression : le log info 'ws.client_gone' a été retiré de "
        "ws.py. Cf. CLAUDE.md section 9 Bug 10."
    )

    # Et un `break` doit suivre dans les 200 caractères suivants
    # (sortie de la boucle pubsub.listen() pour libérer la coroutine).
    after_log = source.split("ws.client_gone")[1]
    assert "break" in after_log[:300], (
        "Bug 10 régression : pas de `break` après le log 'ws.client_gone' "
        "dans ws.py. Sans ce break, la coroutine reste en zombie sur "
        "Redis pubsub → saturation event loop → API hang sur /health. "
        "Cf. CLAUDE.md section 9 Bug 10 (3h de downtime non détecté)."
    )


def test_ws_module_continues_on_payload_parse_error() -> None:
    """SMOKE TEST — vérifie que le bloc `try parse JSON` fait `continue`
    (pas `break`), pour ne pas casser tous les clients si un seul signal
    est mal formé côté publisher.

    Garde-fou complémentaire au précédent : distingue le cas "payload
    invalide" (continue, autres clients gardent leur stream) du cas
    "client gone" (break, ce client uniquement sort).
    """
    from pathlib import Path

    ws_src = Path(__file__).parent.parent / "src" / "tik_core" / "api" / "ws.py"
    source = ws_src.read_text(encoding="utf-8")

    assert 'ws.payload_invalid' in source, (
        "Régression : le log 'ws.payload_invalid' a été retiré. Le bloc "
        "try parse JSON doit logger + continue (cf. Bug 10 fix séparation)."
    )
    after_payload_log = source.split("ws.payload_invalid")[1]
    # Doit y avoir `continue` (pas break) après ce log
    snippet = after_payload_log[:200]
    assert "continue" in snippet, (
        "Régression : pas de `continue` après 'ws.payload_invalid'. "
        "Un payload mal formé doit logger + passer au suivant, pas "
        "déconnecter le client (cf. Bug 10 séparation parse vs send)."
    )
    # Sanity : pas de `break` dans cette section (sinon on coupe les
    # clients pour un seul mauvais payload côté publisher)
    assert "break" not in snippet, (
        "Régression dangereuse : `break` introduit dans le bloc payload "
        "parse. Un seul signal mal formé côté publisher déconnecterait "
        "TOUS les clients abonnés (cf. Bug 10 fix Option A)."
    )


def test_ws_disconnects_cleanly_and_app_stays_healthy(ws_api_key: str) -> None:
    """INTEGRATION TEST Bug 10 — ferme une WS et publie sur Redis derrière.

    Scénario reproducteur (cf. runtime 2026-05-17) :
      1. Client connecte WS
      2. Tik publie un signal sur Redis → WS handler relaie au client
      3. Client se déconnecte brutalement (changement WiFi, swipe down)
      4. Tik publie 5 nouveaux signaux sur Redis
      5. Si bug actif : la coroutine handler retente `send_json` sur WS
         fermée → spam warnings + Redis pubsub zombie → event loop saturé
      6. `/health` doit répondre rapidement (proxy de "event loop sain")

    Skipped si Redis n'est pas accessible localement (CI ou dev sans
    docker compose up).
    """
    import json as _json
    import redis as sync_redis_lib

    settings = get_settings()
    try:
        sync_redis = sync_redis_lib.from_url(settings.redis_url, decode_responses=True)
        sync_redis.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis non accessible pour ce test d'intégration : {exc}")

    fake_payload = _json.dumps({
        "id": "TIK-TEST-BUG10",
        "timestamp": "2026-05-19T10:00:00Z",
        "entity_id": "BTC",
        "horizon": "swing",
        "direction": "neutral",
        "confidence": 0.0,
        "veracity": 0.85,
    })

    with TestClient(app) as client:
        url = f"/api/v1/ws/signals?api_key={ws_api_key}"

        # Étape 1+2 : connexion + publication + réception
        with client.websocket_connect(url) as ws:
            # Publie le signal côté Tik
            sync_redis.publish("tik.signal.BTC.swing", fake_payload)
            # Le handler doit relayer dans la fenêtre (heartbeat 30s, pas
            # de souci de timeout court). receive_json bloque jusqu'à
            # réception ou close.
            msg = ws.receive_json()
            assert msg.get("type") in ("signal", "heartbeat"), (
                f"Réception WS inattendue : {msg!r}"
            )

        # Étape 3 : WS fermée (sortie du context manager `with ws:`).
        # La coroutine handler côté serveur DEVRAIT sortir de la boucle
        # pubsub.listen() au prochain message reçu (try/except + break).

        # Étape 4 : publier 5 signaux pour stresser la coroutine zombie
        # (sans le fix : chaque publish déclenche un warning, accumulant
        # progressivement la saturation).
        for i in range(5):
            sync_redis.publish(
                "tik.signal.BTC.swing",
                _json.dumps({"id": f"TIK-TEST-BUG10-AFTER-{i}", "timestamp": "2026-05-19T10:00:01Z"}),
            )

        # Étape 5+6 : /health doit répondre rapidement (event loop sain).
        # Avec le fix : pas de zombie, /health rapide.
        # Sans le fix : pas immédiat mais avec seulement 5 publications le
        # test pourrait passer quand même (le bug réel a tourné 3h). Le
        # smoke test source code ci-dessus reste plus fiable comme garde-fou
        # mais ce test prouve le scenario bout-en-bout.
        import time
        t0 = time.monotonic()
        response = client.get("/api/v1/health")
        elapsed = time.monotonic() - t0

        assert response.status_code == 200, f"health failed: {response.text}"
        assert elapsed < 2.0, (
            f"/health a mis {elapsed:.2f}s — soupçon de coroutine zombie "
            "qui sature l'event loop (Bug 10)"
        )

    # Cleanup : sync_redis.close() est best-effort
    try:
        sync_redis.close()
    except Exception:  # noqa: BLE001
        pass
