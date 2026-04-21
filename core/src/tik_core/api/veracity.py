"""Endpoints veracity : état global + détail par source."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth import AuthContext, require_scope
from tik_core.storage.database import get_session
from tik_core.storage.models import Source
from tik_core.storage.schemas import SourceVeracity, VeracityStatus

router = APIRouter(prefix="/veracity")


@router.get("/global", response_model=VeracityStatus)
async def global_veracity(
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:veracity")),
) -> VeracityStatus:
    """Moyenne pondérée par tier des sources actives.

    Les sources tier 1 pèsent plus que les tier 5. Si la moyenne
    descend en dessous de 0.4, on considère qu'on est en "collapse"
    (suspicion de désinformation massive ou sources compromises).
    """
    stmt = select(Source).where(Source.active.is_(True))
    result = await session.execute(stmt)
    sources = list(result.scalars().all())

    if not sources:
        return VeracityStatus(
            global_veracity=0.0,
            sources_count_active=0,
            last_computed=datetime.utcnow(),
            status="degraded",
        )

    # Pondération par tier : tier 1 = poids 5, tier 2 = 4, ..., tier 5 = 1
    total_weight = 0.0
    weighted_sum = 0.0
    for s in sources:
        weight = max(1, 6 - s.tier)
        weighted_sum += s.current_veracity * weight
        total_weight += weight

    avg = weighted_sum / total_weight if total_weight else 0.0

    if avg >= 0.7:
        status_str = "healthy"
    elif avg >= 0.4:
        status_str = "degraded"
    else:
        status_str = "collapse"

    return VeracityStatus(
        global_veracity=round(avg, 4),
        sources_count_active=len(sources),
        last_computed=datetime.utcnow(),
        status=status_str,
    )


@router.get("/sources", response_model=list[SourceVeracity])
async def list_sources(
    active_only: bool = True,
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:veracity")),
) -> list[Source]:
    stmt = select(Source).order_by(Source.tier, Source.id)
    if active_only:
        stmt = stmt.where(Source.active.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/sources/{source_id}", response_model=SourceVeracity)
async def get_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:veracity")),
) -> Source:
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source
