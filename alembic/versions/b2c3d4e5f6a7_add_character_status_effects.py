"""add character status effects

Permanent, sheet-level status effects for characters: how they modify the
character's rolls (affects / roll_modifier / advantage) and which other
characters' presence negates them (negated_by). Campaign-scoped temporary
conditions stay in ``campaign_participants.state``; this table is for the
traits that travel with the character across campaigns.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-29 18:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'character_status_effects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('affects', sa.Text(), nullable=False),
        sa.Column('roll_modifier', sa.Integer(), nullable=False),
        sa.Column('advantage', sa.String(), nullable=False),
        sa.Column('negated_by', postgresql.JSONB(), nullable=False),
        sa.Column('negation_condition', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('character_id', 'name', name='uq_character_status_effects_character_name'),
    )
    op.create_index(op.f('ix_character_status_effects_character_id'), 'character_status_effects', ['character_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_character_status_effects_character_id'), table_name='character_status_effects')
    op.drop_table('character_status_effects')
