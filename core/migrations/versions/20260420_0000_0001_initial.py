"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ----- entities -----
    op.create_table(
        "entities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_entities_domain", "entities", ["domain"])

    # ----- sources -----
    op.create_table(
        "sources",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("base_veracity", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("current_veracity", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("tier", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sources_category", "sources", ["category"])

    # ----- signals (hypertable timescale) -----
    op.create_table(
        "signals",
        sa.Column("id", sa.String(64), primary_key=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("veracity", sa.Float(), nullable=False),
        sa.Column("hypothesis", sa.Text()),
        sa.Column("counter_scenarios", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("triggers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("sources_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expiry", sa.DateTime()),
        sa.Column("advisory", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("circuit_breaker_status", sa.String(32), nullable=False, server_default="ok"),
        sa.PrimaryKeyConstraint("id", "timestamp"),
                sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_signals_timestamp", "signals", ["timestamp"])
    op.create_index("ix_signals_entity_id", "signals", ["entity_id"])
    op.create_index("ix_signals_horizon", "signals", ["horizon"])

    # Hypertable TimescaleDB — partitionnement par timestamp (intervalle 7j)
    op.execute(
        "SELECT create_hypertable("
        "'signals', 'timestamp', "
        "chunk_time_interval => INTERVAL '7 days', "
        "if_not_exists => TRUE"
        ")"
    )

    # ----- feedbacks -----
    op.create_table(
        "feedbacks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("signal_id", sa.String(64), nullable=False),
                sa.Column("signal_timestamp", sa.DateTime(), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("trade_id", sa.String(128)),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("pnl_points", sa.Float()),
        sa.Column("pnl_pct", sa.Float()),
        sa.Column("duration_held_s", sa.Integer()),
        sa.Column("exit_reason", sa.String(64)),
        sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
                sa.ForeignKeyConstraint(["signal_id", "signal_timestamp"], ["signals.id", "signals.timestamp"], ondelete="CASCADE"),
    )
    op.create_index("ix_feedbacks_signal_id", "feedbacks", ["signal_id"])
    op.create_index("ix_feedbacks_client_id", "feedbacks", ["client_id"])

    # ----- api_keys -----
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False, unique=True),
        sa.Column("key_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("key_suffix", sa.String(8), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime()),
    )

    # ----- seed minimal des sources connues -----
    op.execute(
        """
        INSERT INTO sources (id, name, category, base_veracity, current_veracity, tier, active, metadata_json, created_at)
        VALUES
          ('binance', 'Binance Exchange', 'exchange', 0.95, 0.95, 1, true, '{}', now()),
          ('yahoo', 'Yahoo Finance', 'exchange', 0.85, 0.85, 2, true, '{}', now()),
          ('fred', 'FRED (Federal Reserve)', 'macro', 0.98, 0.98, 1, true, '{}', now()),
          ('coingecko', 'CoinGecko', 'aggregator', 0.85, 0.85, 2, true, '{}', now()),
          ('reuters', 'Reuters', 'news', 0.95, 0.95, 1, true, '{}', now()),
          ('bloomberg', 'Bloomberg', 'news', 0.95, 0.95, 1, true, '{}', now()),
          ('cryptopanic', 'CryptoPanic', 'news', 0.70, 0.70, 3, true, '{}', now()),
          ('polymarket', 'Polymarket', 'predictive', 0.75, 0.75, 2, true, '{}', now()),
          ('reddit', 'Reddit', 'social', 0.40, 0.40, 4, true, '{}', now())
        """
    )

    # ----- seed minimal des entities trading BTC + GOLD -----
    op.execute(
        """
        INSERT INTO entities (id, domain, namespace, metadata_json, active, created_at, updated_at)
        VALUES
          ('BTC', 'trading', 'crypto', '{"asset_class":"crypto","quote_currency":"USDT"}', true, now(), now()),
          ('GOLD', 'trading', 'commodity', '{"asset_class":"commodity","quote_currency":"USD"}', true, now(), now())
        """
    )


def downgrade() -> None:
    op.drop_table("api_keys")
    op.drop_index("ix_feedbacks_client_id", table_name="feedbacks")
    op.drop_index("ix_feedbacks_signal_id", table_name="feedbacks")
    op.drop_table("feedbacks")
    op.drop_index("ix_signals_horizon", table_name="signals")
    op.drop_index("ix_signals_entity_id", table_name="signals")
    op.drop_index("ix_signals_timestamp", table_name="signals")
    op.drop_table("signals")
    op.drop_index("ix_sources_category", table_name="sources")
    op.drop_table("sources")
    op.drop_index("ix_entities_domain", table_name="entities")
    op.drop_table("entities")
