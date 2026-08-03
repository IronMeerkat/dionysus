"""add routing exemplars table for cheap OOC-vs-story routing

Creates ``routing_exemplars``: labeled (``ooc`` | ``story``) example player
messages with their embeddings. The DM's intent router votes over the
nearest exemplars and skips the per-turn LLM intent classification when the
vote is confident. Small table by design (~100 rows), so no ivfflat index.

Seed with ``scripts/seed_routing_exemplars.py``.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-31 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'routing_exemplars',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1024), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_routing_exemplars_label', 'routing_exemplars', ['label'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_routing_exemplars_label', table_name='routing_exemplars')
    op.drop_table('routing_exemplars')
