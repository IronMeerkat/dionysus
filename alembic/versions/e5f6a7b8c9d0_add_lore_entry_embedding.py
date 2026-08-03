"""add lore entry embedding column for vector lore recall

Adds a nullable pgvector ``embedding`` column to ``lore_entries`` so the
DM's intent router can retrieve relevant lore via l2-distance search
over the player's message, instead of reading a catalog of every title
and picking ids. An ivfflat index accelerates the per-world scan path.

Existing rows are left NULL; run ``scripts/vectorize_lore_entries.py``
to backfill them with the shared Ollama embedder.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-31 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'lore_entries',
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1024), nullable=True),
    )
    # The btree index on world_id (from the model) handles the per-world
    # filter; ivfflat covers the vector scan. l2 ops match the
    # euclidean_distance recall metric (same as character memories).
    op.execute(
        "CREATE INDEX ix_lore_entries_embedding "
        "ON lore_entries USING ivfflat (embedding vector_l2_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_lore_entries_embedding")
    op.drop_column('lore_entries', 'embedding')
