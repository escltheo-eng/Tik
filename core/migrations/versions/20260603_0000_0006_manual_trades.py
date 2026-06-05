"""add manual_trades table — carnet de trades manuels (Levier B 2026-06-03)

Revision ID: 0006_manual_trades
Revises: 0005_macro_events
Create Date: 2026-06-03 00:00:00.000000

Rendre l'utilité réelle de Tik mesurable : journal des vrais trades de la
trader + snapshot du contexte Tik à l'entrée (direction/véracité/alignement)
pour mesurer « trader AVEC Tik vs CONTRE vs SANS ». Cf. modèle ManualTrade.

Migration purement additive (CREATE TABLE) : aucun impact sur les données
existantes, déploiement sans risque.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_manual_trades"
down_revision: Union[str, None] = "0005_macro_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manual_trades",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("entry_time", sa.DateTime(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("size_lots", sa.Float(), nullable=False),
        sa.Column("stop_price", sa.Float(), nullable=True),
        sa.Column("target_price", sa.Float(), nullable=True),
        sa.Column("exit_time", sa.DateTime(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("result_pct", sa.Float(), nullable=True),
        sa.Column("tik_signal_id", sa.String(64), nullable=True),
        sa.Column("tik_direction", sa.String(16), nullable=True),
        sa.Column("tik_veracity", sa.Float(), nullable=True),
        sa.Column("tik_alignment", sa.String(16), nullable=True),
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
    )
    op.create_index("ix_manual_trades_entity_id", "manual_trades", ["entity_id"])
    op.create_index("ix_manual_trades_entry_time", "manual_trades", ["entry_time"])
    op.create_index("ix_manual_trades_status", "manual_trades", ["status"])


def downgrade() -> None:
    op.drop_index("ix_manual_trades_status", table_name="manual_trades")
    op.drop_index("ix_manual_trades_entry_time", table_name="manual_trades")
    op.drop_index("ix_manual_trades_entity_id", table_name="manual_trades")
    op.drop_table("manual_trades")
