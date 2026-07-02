"""add world state tables, campaign contract and world clock

Revision ID: 8c4be51f0d27
Revises: 56e360eaad6f
Create Date: 2026-06-12 23:05:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '8c4be51f0d27'
down_revision: Union[str, Sequence[str], None] = '56e360eaad6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_CONTRACT = {
    "tone": "dark-adventure",
    "rules_strictness": "medium",
    "lethality": "medium",
    "humor": "allowed",
    "gore": "medium",
    "romance": "allowed",
    "railroading": "forbidden",
    "player_agency": "sacred",
}


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'quest_threads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_quest_threads_campaign_id'), 'quest_threads', ['campaign_id'], unique=False)

    op.create_table(
        'faction_clocks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('faction_name', sa.String(), nullable=False),
        sa.Column('goal', sa.Text(), nullable=False),
        sa.Column('ticks_current', sa.Integer(), nullable=False),
        sa.Column('ticks_max', sa.Integer(), nullable=False),
        sa.Column('next_move', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_faction_clocks_campaign_id'), 'faction_clocks', ['campaign_id'], unique=False)

    op.add_column(
        'campaigns',
        sa.Column(
            'contract',
            JSONB(),
            nullable=False,
            server_default=sa.text(f"'{json.dumps(DEFAULT_CONTRACT)}'::jsonb"),
        ),
    )
    op.add_column(
        'conversations',
        sa.Column('world_clock', sa.String(), nullable=True, server_default=''),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversations', 'world_clock')
    op.drop_column('campaigns', 'contract')
    op.drop_index(op.f('ix_faction_clocks_campaign_id'), table_name='faction_clocks')
    op.drop_table('faction_clocks')
    op.drop_index(op.f('ix_quest_threads_campaign_id'), table_name='quest_threads')
    op.drop_table('quest_threads')
