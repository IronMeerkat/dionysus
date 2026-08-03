"""add character embedding for semantic NPC dedup

Adds a nullable pgvector ``embedding`` column to ``characters`` (payload:
``name + description``) so the DM planner can detect when a planned NPC
introduction matches an existing character and skip the build loop. An
ivfflat index accelerates the vector scan.

Existing rows are left NULL; run ``scripts/vectorize_characters.py`` to
backfill them with the shared Ollama embedder.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-31 21:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'characters',
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1024), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_characters_embedding "
        "ON characters USING ivfflat (embedding vector_l2_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_characters_embedding")
    op.drop_column('characters', 'embedding')
