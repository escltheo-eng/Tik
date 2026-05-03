"""add source_credibility_history table

Revision ID: 0003_source_credibility_history
Revises: 0002_backtest_runs
Create Date: 2026-05-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_source_credibility_history"
down_revision: Union[str, None] = "0002_backtest_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_credibility_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("previous_score", sa.Float(), nullable=True),
        sa.Column("hit_rate", sa.Float(), nullable=True),
        sa.Column("samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lookback_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("adjustment", sa.String(16), nullable=False, server_default="unchanged"),
    )
    op.create_index(
        "ix_source_credibility_history_source",
        "source_credibility_history",
        ["source"],
    )
    op.create_index(
        "ix_source_credibility_history_computed_at",
        "source_credibility_history",
        ["computed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_credibility_history_computed_at",
        table_name="source_credibility_history",
    )
    op.drop_index(
        "ix_source_credibility_history_source",
        table_name="source_credibility_history",
    )
    op.drop_table("source_credibility_history")
