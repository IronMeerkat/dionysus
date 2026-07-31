"""add message embedding column for campaign vector recall

Adds an nullable pgvector ``embedding`` column to ``messages`` so every
message sent in play can be embedded at persist time and recalled via
euclidean-distance search by the merged campaign-admin agent's
``search_campaign_messages`` tool. An ivfflat index over
``(conversation_id, embedding)`` accelerates the per-campaign scan path.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-30 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'messages',
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1024), nullable=True),
    )
    # ivfflat does not support multicolumn indexes, so the vector index is
    # on the embedding column alone; the existing btree index on
    # conversation_id (from the model) lets the search path filter by
    # campaign cheaply enough. 100 lists is a sane default for a messages
    # table that grows with play. l2 ops match the euclidean_distance
    # recall metric shared with lore and character memories.
    op.execute(
        "CREATE INDEX ix_messages_embedding "
        "ON messages USING ivfflat (embedding vector_l2_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_messages_embedding")
    op.drop_column('messages', 'embedding')
