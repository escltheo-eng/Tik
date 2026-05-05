"""add macro_events table for macro/geopolitical calendar (Lacune B Phase B1 J+10)

Revision ID: 0005_macro_events
Revises: 0004_headlines
Create Date: 2026-05-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_macro_events"
down_revision: Union[str, None] = "0004_headlines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "macro_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_code", sa.String(64), nullable=False),
        sa.Column("event_name", sa.String(128), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(), nullable=False),
        sa.Column("importance", sa.String(16), nullable=False),
        sa.Column("assets_impacted", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "event_code", "scheduled_for", name="uq_macro_events_code_when"
        ),
    )
    op.create_index("ix_macro_events_event_code", "macro_events", ["event_code"])
    op.create_index(
        "ix_macro_events_scheduled_for", "macro_events", ["scheduled_for"]
    )
    op.create_index("ix_macro_events_importance", "macro_events", ["importance"])


def downgrade() -> None:
    op.drop_index("ix_macro_events_importance", table_name="macro_events")
    op.drop_index("ix_macro_events_scheduled_for", table_name="macro_events")
    op.drop_index("ix_macro_events_event_code", table_name="macro_events")
    op.drop_table("macro_events")
