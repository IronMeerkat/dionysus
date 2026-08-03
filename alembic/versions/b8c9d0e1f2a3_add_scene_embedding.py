"""add scene embedding to world state for the drift gate

Adds a nullable pgvector ``scene_embedding`` column to ``world_state``: the
centroid of the last summarized scene's message embeddings. The epilogue
compares the current window's centroid against it and skips the
scene-change LLM check when the drift is below ``tau_drift``. One row per
campaign, so no index.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-31 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'world_state',
        sa.Column('scene_embedding', pgvector.sqlalchemy.Vector(1024), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('world_state', 'scene_embedding')
