"""add headlines table for OSINT audit historical storage (Lacune A J+10)

Revision ID: 0004_headlines
Revises: 0003_source_credibility_history
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_headlines"
down_revision: Union[str, None] = "0003_source_credibility_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "headlines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("title_hash", sa.String(16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "publisher",
            sa.String(128),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("sentiment", sa.String(16), nullable=False),
        sa.Column("credibility", sa.Float(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_headlines_entity_id", "headlines", ["entity_id"])
    op.create_index("ix_headlines_source", "headlines", ["source"])
    op.create_index("ix_headlines_title_hash", "headlines", ["title_hash"])
    op.create_index("ix_headlines_fetched_at", "headlines", ["fetched_at"])


def downgrade() -> None:
    op.drop_index("ix_headlines_fetched_at", table_name="headlines")
    op.drop_index("ix_headlines_title_hash", table_name="headlines")
    op.drop_index("ix_headlines_source", table_name="headlines")
    op.drop_index("ix_headlines_entity_id", table_name="headlines")
    op.drop_table("headlines")
