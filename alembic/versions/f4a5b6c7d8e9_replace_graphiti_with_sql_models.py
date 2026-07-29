"""replace graphiti with sql models for worlds, lore, memories, events, secrets, prefs

Postgres becomes the single source of truth for everything that used to live
in Neo4j: lore worlds + markdown entries, character memories (pgvector),
world events, DM secrets, and player preferences. Campaigns now point at a
real worlds row instead of carrying a lore_world string.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-07-29 16:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table('worlds',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_worlds_name'), 'worlds', ['name'], unique=True)

    op.create_table('lore_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('world_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lore_entries_world_id'), 'lore_entries', ['world_id'], unique=False)

    op.create_table('character_memories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1024), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_character_memories_campaign_id'), 'character_memories', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_character_memories_character_id'), 'character_memories', ['character_id'], unique=False)

    op.create_table('world_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_world_events_campaign_id'), 'world_events', ['campaign_id'], unique=False)

    op.create_table('dm_secrets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dm_secrets_campaign_id'), 'dm_secrets', ['campaign_id'], unique=False)

    op.create_table('player_preferences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_player_preferences_campaign_id'), 'player_preferences', ['campaign_id'], unique=False)

    # Move campaigns.lore_world (string) to campaigns.world_id (FK).
    op.add_column('campaigns', sa.Column('world_id', sa.Integer(), nullable=True))
    op.execute(
        """
        INSERT INTO worlds (name, description, created_at, updated_at)
        SELECT DISTINCT lore_world, '', now(), now() FROM campaigns
        ON CONFLICT (name) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE campaigns SET world_id = worlds.id
        FROM worlds WHERE worlds.name = campaigns.lore_world
        """
    )
    op.alter_column('campaigns', 'world_id', nullable=False)
    op.create_index(op.f('ix_campaigns_world_id'), 'campaigns', ['world_id'], unique=False)
    op.create_foreign_key('campaigns_world_id_fkey', 'campaigns', 'worlds', ['world_id'], ['id'])
    op.drop_column('campaigns', 'lore_world')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('campaigns', sa.Column('lore_world', sa.String(), nullable=True))
    op.execute(
        """
        UPDATE campaigns SET lore_world = worlds.name
        FROM worlds WHERE worlds.id = campaigns.world_id
        """
    )
    op.alter_column('campaigns', 'lore_world', nullable=False)
    op.drop_constraint('campaigns_world_id_fkey', 'campaigns', type_='foreignkey')
    op.drop_index(op.f('ix_campaigns_world_id'), table_name='campaigns')
    op.drop_column('campaigns', 'world_id')

    op.drop_index(op.f('ix_player_preferences_campaign_id'), table_name='player_preferences')
    op.drop_table('player_preferences')
    op.drop_index(op.f('ix_dm_secrets_campaign_id'), table_name='dm_secrets')
    op.drop_table('dm_secrets')
    op.drop_index(op.f('ix_world_events_campaign_id'), table_name='world_events')
    op.drop_table('world_events')
    op.drop_index(op.f('ix_character_memories_character_id'), table_name='character_memories')
    op.drop_index(op.f('ix_character_memories_campaign_id'), table_name='character_memories')
    op.drop_table('character_memories')
    op.drop_index(op.f('ix_lore_entries_world_id'), table_name='lore_entries')
    op.drop_table('lore_entries')
    op.drop_index(op.f('ix_worlds_name'), table_name='worlds')
    op.drop_table('worlds')
