"""Endpoint feedback : les bots clients renvoient leurs outcomes.

Ces données nourrissent le calibrage continu des engines et des pondérations
de sources.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth import AuthContext, require_scope
from tik_core.storage.database import get_session
from tik_core.storage.models import Feedback, Signal
from tik_core.storage.schemas import FeedbackIn, FeedbackOut

router = APIRouter(prefix="/feedback")


@router.post("", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    payload: FeedbackIn,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scope("write:feedback")),
) -> Feedback:
    # Vérifier que le signal existe
    signal = await session.get(Signal, payload.signal_id)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal '{payload.signal_id}' not found",
        )

    fb = Feedback(
        signal_id=payload.signal_id,
        # `signals.timestamp` fait partie de la PK composite côté hypertable
        # Timescale (Bug 1/2) et `feedbacks.signal_timestamp` est NOT NULL.
        # On le reprend du signal qu'on vient de charger — sans ça l'INSERT
        # lève NotNullViolation (endpoint jamais exercé jusqu'ici, SDK gelé →
        # bug latent capté par test_feedback_api le 2026-06-01).
        signal_timestamp=signal.timestamp,
        client_id=ctx.client_id,
        trade_id=payload.trade_id,
        outcome=payload.outcome,
        pnl_points=payload.pnl_points,
        pnl_pct=payload.pnl_pct,
        duration_held_s=payload.duration_held_s,
        exit_reason=payload.exit_reason,
    )
    session.add(fb)
    await session.flush()
    return fb
