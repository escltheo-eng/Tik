"""CRUD entities observées par Tik (BTC, GOLD, event_X...)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth import AuthContext, require_scope
from tik_core.storage.database import get_session
from tik_core.storage.models import Entity
from tik_core.storage.schemas import EntityIn, EntityOut
from tik_core.utils.time import now_utc_naive

router = APIRouter(prefix="/entities")


@router.get("", response_model=list[EntityOut])
async def list_entities(
    active_only: bool = True,
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:entities")),
) -> list[Entity]:
    stmt = select(Entity)
    if active_only:
        stmt = stmt.where(Entity.active.is_(True))
    stmt = stmt.order_by(Entity.id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=EntityOut, status_code=status.HTTP_201_CREATED)
async def create_entity(
    payload: EntityIn,
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("write:entities")),
) -> Entity:
    existing = await session.get(Entity, payload.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Entity '{payload.id}' already exists",
        )
    entity = Entity(
        id=payload.id,
        domain=payload.domain,
        namespace=payload.namespace,
        metadata_json=payload.metadata,
        active=True,
        created_at=now_utc_naive(),
        updated_at=now_utc_naive(),
    )
    session.add(entity)
    await session.flush()
    return entity


@router.get("/{entity_id}", response_model=EntityOut)
async def get_entity(
    entity_id: str,
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:entities")),
) -> Entity:
    entity = await session.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_entity(
    entity_id: str,
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("write:entities")),
) -> None:
    """Soft delete : désactive mais garde l'historique."""
    entity = await session.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    entity.active = False
    entity.updated_at = now_utc_naive()
