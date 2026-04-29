"""add backtest_runs table

Revision ID: 0002_backtest_runs
Revises: 0001_initial
Create Date: 2026-04-29 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_backtest_runs"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("threshold_pct", sa.Float(), nullable=False),
        sa.Column("total_signals", sa.Integer(), nullable=False),
        sa.Column("n_eligible", sa.Integer(), nullable=False),
        sa.Column("n_evaluated", sa.Integer(), nullable=False),
        sa.Column("hit_rate", sa.Float(), nullable=False),
        sa.Column("avg_gain_pct", sa.Float(), nullable=False),
        sa.Column("stats_by_entity", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("stats_by_veracity", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("baselines", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_backtest_runs_run_at",
        "backtest_runs",
        ["run_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_runs_run_at", table_name="backtest_runs")
    op.drop_table("backtest_runs")
