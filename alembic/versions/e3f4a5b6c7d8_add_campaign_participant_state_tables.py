"""add campaign participant state tables (CampaignPlayer, CampaignNPC)

Per-(campaign, player) and per-(campaign, character) live mechanical state:
stats, status effects, modifiers and freeform notes, all stored in a single
JSONB ``state`` column so the schema stays flexible. Foreign keys are real
columns; everything else is JSON. An empty blob means "no tracked mechanical
state" and the game plays as pure narrative.

Revision ID: e3f4a5b6c7d8
Revises: 9d2a7f1c4b6e
Create Date: 2026-07-02 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = '9d2a7f1c4b6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'campaign_players',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('state', JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.ForeignKeyConstraint(['player_id'], ['players.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('campaign_id', 'player_id', name='uq_campaign_players_campaign_player'),
    )
    op.create_index(op.f('ix_campaign_players_campaign_id'), 'campaign_players', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_campaign_players_player_id'), 'campaign_players', ['player_id'], unique=False)

    op.create_table(
        'campaign_npcs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=False),
        sa.Column('state', JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('campaign_id', 'character_id', name='uq_campaign_npcs_campaign_character'),
    )
    op.create_index(op.f('ix_campaign_npcs_campaign_id'), 'campaign_npcs', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_campaign_npcs_character_id'), 'campaign_npcs', ['character_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_campaign_npcs_character_id'), table_name='campaign_npcs')
    op.drop_index(op.f('ix_campaign_npcs_campaign_id'), table_name='campaign_npcs')
    op.drop_table('campaign_npcs')
    op.drop_index(op.f('ix_campaign_players_player_id'), table_name='campaign_players')
    op.drop_index(op.f('ix_campaign_players_campaign_id'), table_name='campaign_players')
    op.drop_table('campaign_players')
