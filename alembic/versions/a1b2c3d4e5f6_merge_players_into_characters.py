"""merge players into characters

Players and characters become one concept: any character is playable and any
character can be an NPC; which character is the PC is decided per conversation.

Data migration:
1. Copy every ``players`` row into ``characters`` (name collisions map onto the
   existing character with that name).
2. Copy ``player_descriptions`` into ``character_descriptions``; on a name
   collision the player's versions are offset after the character's existing
   versions so per-character version numbers stay monotonic.
3. Repoint ``conversations.player_id`` at ``characters`` (values remapped via
   the name join).
4. Merge ``campaign_npcs`` + ``campaign_players`` into a single
   ``campaign_participants`` table.
5. Drop the player-only tables.

The downgrade recreates the player tables but cannot split merged characters
back apart -- it only restores the schema, not the data division.

Revision ID: a1b2c3d4e5f6
Revises: f4a5b6c7d8e9
Create Date: 2026-07-29 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Copy players into characters; name collisions reuse the existing row.
    op.execute(
        """
        INSERT INTO characters (name, created_at)
        SELECT p.name, p.created_at FROM players p
        WHERE NOT EXISTS (SELECT 1 FROM characters c WHERE c.name = p.name)
        """
    )

    # 2. Copy player descriptions, offsetting versions past any existing
    #    character versions when the name collided.
    op.execute(
        """
        INSERT INTO character_descriptions (character_id, version, body, created_at)
        SELECT
            c.id,
            pd.version + COALESCE((
                SELECT MAX(cd.version) FROM character_descriptions cd
                WHERE cd.character_id = c.id
            ), 0),
            pd.body,
            pd.created_at
        FROM player_descriptions pd
        JOIN players p ON p.id = pd.player_id
        JOIN characters c ON c.name = p.name
        """
    )

    # 3. Repoint conversations.player_id at characters. The old FK to players
    #    must go first -- the remapped character ids do not exist in players.
    op.drop_constraint('conversations_player_id_fkey', 'conversations', type_='foreignkey')
    op.execute(
        """
        UPDATE conversations conv SET player_id = c.id
        FROM players p
        JOIN characters c ON c.name = p.name
        WHERE conv.player_id = p.id
        """
    )
    op.create_foreign_key(
        'conversations_player_id_fkey', 'conversations', 'characters',
        ['player_id'], ['id'],
    )

    # 4. Merge both participant-state tables into campaign_participants.
    op.create_table(
        'campaign_participants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=False),
        sa.Column('state', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('campaign_id', 'character_id', name='uq_campaign_participants_campaign_character'),
    )
    op.create_index(op.f('ix_campaign_participants_campaign_id'), 'campaign_participants', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_campaign_participants_character_id'), 'campaign_participants', ['character_id'], unique=False)

    op.execute(
        """
        INSERT INTO campaign_participants (campaign_id, character_id, state, created_at, updated_at)
        SELECT campaign_id, character_id, state, created_at, updated_at FROM campaign_npcs
        """
    )
    op.execute(
        """
        INSERT INTO campaign_participants (campaign_id, character_id, state, created_at, updated_at)
        SELECT cp.campaign_id, c.id, cp.state, cp.created_at, cp.updated_at
        FROM campaign_players cp
        JOIN players p ON p.id = cp.player_id
        JOIN characters c ON c.name = p.name
        ON CONFLICT (campaign_id, character_id) DO NOTHING
        """
    )

    # 5. Drop the player-only tables.
    op.drop_index(op.f('ix_campaign_players_player_id'), table_name='campaign_players')
    op.drop_index(op.f('ix_campaign_players_campaign_id'), table_name='campaign_players')
    op.drop_table('campaign_players')
    op.drop_index(op.f('ix_campaign_npcs_character_id'), table_name='campaign_npcs')
    op.drop_index(op.f('ix_campaign_npcs_campaign_id'), table_name='campaign_npcs')
    op.drop_table('campaign_npcs')
    op.drop_index(op.f('ix_player_descriptions_player_id'), table_name='player_descriptions')
    op.drop_table('player_descriptions')
    op.drop_index(op.f('ix_players_name'), table_name='players')
    op.drop_table('players')


def downgrade() -> None:
    """Recreate the player-side schema (data division is not restored)."""
    op.create_table(
        'players',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_players_name'), 'players', ['name'], unique=True)

    op.create_table(
        'player_descriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_player_descriptions_player_id'), 'player_descriptions', ['player_id'], unique=False)

    op.create_table(
        'campaign_players',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('state', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
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
        sa.Column('state', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('campaign_id', 'character_id', name='uq_campaign_npcs_campaign_character'),
    )
    op.create_index(op.f('ix_campaign_npcs_campaign_id'), 'campaign_npcs', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_campaign_npcs_character_id'), 'campaign_npcs', ['character_id'], unique=False)

    # Copy NPC rows back; player rows cannot be recovered.
    op.execute(
        """
        INSERT INTO campaign_npcs (campaign_id, character_id, state, created_at, updated_at)
        SELECT campaign_id, character_id, state, created_at, updated_at FROM campaign_participants
        """
    )
    op.drop_index(op.f('ix_campaign_participants_character_id'), table_name='campaign_participants')
    op.drop_index(op.f('ix_campaign_participants_campaign_id'), table_name='campaign_participants')
    op.drop_table('campaign_participants')

    op.drop_constraint('conversations_player_id_fkey', 'conversations', type_='foreignkey')
    op.execute("UPDATE conversations SET player_id = NULL")
    op.create_foreign_key(
        'conversations_player_id_fkey', 'conversations', 'players',
        ['player_id'], ['id'],
    )
