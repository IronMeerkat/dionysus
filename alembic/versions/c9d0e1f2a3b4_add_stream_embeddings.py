"""add embeddings to campaign streams for relevance-filtered recall

Adds a nullable pgvector ``embedding`` column to ``world_events``,
``dm_secrets``, and ``player_preferences`` so the DM context can recall
topically relevant facts (unioned with the freshest rows) instead of only
the last N rows. ``world_events`` grows fastest and gets an ivfflat index;
the other two stay plain columns until size demands.

Existing rows are left NULL; run ``scripts/vectorize_campaign_streams.py``
to backfill them with the shared Ollama embedder.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-31 21:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for table in ('world_events', 'dm_secrets', 'player_preferences'):
        op.add_column(
            table,
            sa.Column('embedding', pgvector.sqlalchemy.Vector(1024), nullable=True),
        )
    op.execute(
        "CREATE INDEX ix_world_events_embedding "
        "ON world_events USING ivfflat (embedding vector_l2_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_world_events_embedding")
    for table in ('player_preferences', 'dm_secrets', 'world_events'):
        op.drop_column(table, 'embedding')
