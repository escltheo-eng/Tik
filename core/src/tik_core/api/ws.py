"""WebSocket endpoint — stream des signaux live.

Connexion : `ws://host:8200/api/v1/ws/signals?api_key=<key>&entity=BTC&horizon=swing`

Auth via query param `api_key` (car les headers sont limités sur WS navigateur).
"""

import asyncio
import json

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth.api_key import hash_key
from tik_core.config import get_settings

# IMPORTANT: import the module, NOT the variable. The module attribute
# `_session_maker` is set asynchronously by `init_engine()` during the
# FastAPI lifespan startup. Importing the variable directly (i.e.
# `from ...database import _session_maker`) freezes it to its value at
# import time (which is `None`), so every WS would close with 1011 and
# the client would see a 403 forever. Accessing `database._session_maker`
# at runtime ensures we read the live value.
from tik_core.storage import database
from tik_core.storage.models import ApiKey

log = structlog.get_logger()
router = APIRouter()


async def _authenticate_ws(api_key: str, session: AsyncSession) -> ApiKey | None:
    """Valide la clé API (équivalent WS de ApiKeyProvider)."""
    key_hash_value = hash_key(api_key)
    stmt = select(ApiKey).where(ApiKey.key_hash == key_hash_value)
    result = await session.execute(stmt)
    key = result.scalar_one_or_none()
    if key is None or not key.active:
        return None
    return key


@router.websocket("/ws/signals")
async def ws_signals(
    websocket: WebSocket,
    api_key: str = Query(..., description="API key for authentication"),
    entity: str | None = Query(None),
    horizon: str | None = Query(None),
) -> None:
    """Stream des signaux en temps réel.

    Filtre optionnel par entity et/ou horizon.
    Écoute le canal Redis `tik.signal.*` et relaie les messages correspondants.
    """
    # Auth — read session_maker dynamically from the database module
    # (cf. import comment above for why we don't bind it at import time).
    session_maker = database._session_maker
    if session_maker is None:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    async with session_maker() as session:
        key = await _authenticate_ws(api_key, session)
        if key is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await websocket.accept()
    log.info("ws.connected", client_id=key.client_id, entity=entity, horizon=horizon)

    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = redis.pubsub()

    # Pattern de souscription
    # tik.signal.<entity>.<horizon>
    entity_pat = entity or "*"
    horizon_pat = horizon or "*"
    pattern = f"tik.signal.{entity_pat}.{horizon_pat}"
    await pubsub.psubscribe(pattern)

    # Heartbeat toutes les 30s
    async def _heartbeat() -> None:
        try:
            while True:
                await asyncio.sleep(30)
                await websocket.send_json({"type": "heartbeat"})
        except Exception:
            return

    hb_task = asyncio.create_task(_heartbeat())

    try:
        async for message in pubsub.listen():
            if message is None:
                continue
            if message.get("type") not in ("pmessage", "message"):
                continue
            data = message.get("data")
            if not data:
                continue
            try:
                parsed = json.loads(data) if isinstance(data, str) else data
            except (json.JSONDecodeError, TypeError) as exc:
                # Payload mal formé côté publisher — on log et on continue
                # avec le message suivant (les autres clients reçoivent OK).
                log.warning("ws.payload_invalid", error=str(exc))
                continue
            try:
                await websocket.send_json({"type": "signal", "payload": parsed})
            except Exception as exc:  # noqa: BLE001
                # Client déconnecté (RuntimeError "Cannot call 'send' once a
                # close message has been sent." / ConnectionClosed). Sortie
                # de la boucle pour laisser le finally libérer pubsub/redis,
                # sinon coroutine zombie qui spam les warnings à chaque
                # nouveau signal Redis publié → event loop sature → API
                # FastAPI hang sur /api/v1/* (cf. bug runtime 2026-05-17).
                log.info("ws.client_gone", client_id=key.client_id, error=str(exc))
                break
    except WebSocketDisconnect:
        log.info("ws.disconnected", client_id=key.client_id)
    finally:
        hb_task.cancel()
        await pubsub.punsubscribe(pattern)
        await pubsub.close()
        await redis.close()
