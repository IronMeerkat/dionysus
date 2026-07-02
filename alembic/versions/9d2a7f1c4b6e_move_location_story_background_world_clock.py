"""move location, story_background, world_clock out of conversations

Location, story_background and world_clock were per-conversation columns but are
really campaign-level concerns:

  * story_background is static campaign flavor -> moved to campaigns.story_background
  * location + world_clock are live, advancing world state -> moved to a new
    world_state table (1:1 with campaigns)

Because a campaign may have many conversations, each with its own values, the
upgrade collapses them to one value per campaign using the most-recent
conversation (by updated_at, then id). The downgrade restores a flat per-
conversation value from the campaign-level rows.

Revision ID: 9d2a7f1c4b6e
Revises: 8c4be51f0d27
Create Date: 2026-07-02 11:36:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d2a7f1c4b6e'
down_revision: Union[str, Sequence[str], None] = '8c4be51f0d27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. story_background becomes a campaign column.
    op.add_column(
        'campaigns',
        sa.Column('story_background', sa.Text(), nullable=False, server_default=''),
    )

    # 2. New 1:1 world_state table holding the live location + narrative clock.
    op.create_table(
        'world_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('location', sa.String(), nullable=False, server_default=''),
        sa.Column('world_clock', sa.String(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('campaign_id', name='uq_world_state_campaign_id'),
    )
    op.create_index(op.f('ix_world_state_campaign_id'), 'world_state', ['campaign_id'], unique=True)

    # 3. Backfill campaigns.story_background from the most-recent conversation.
    op.execute("""
        UPDATE campaigns c
        SET story_background = sub.story_background
        FROM (
            SELECT DISTINCT ON (campaign_id)
                   campaign_id, story_background
            FROM conversations
            WHERE story_background IS NOT NULL AND story_background <> ''
            ORDER BY campaign_id, updated_at DESC, id DESC
        ) sub
        WHERE c.id = sub.campaign_id
    """)

    # 4. Backfill one world_state row per campaign from its most-recent conversation.
    op.execute("""
        INSERT INTO world_state (campaign_id, location, world_clock, created_at, updated_at)
        SELECT sub.campaign_id,
               COALESCE(sub.location, ''),
               COALESCE(sub.world_clock, ''),
               now(), now()
        FROM (
            SELECT DISTINCT ON (campaign_id)
                   campaign_id, location, world_clock
            FROM conversations
            ORDER BY campaign_id, updated_at DESC, id DESC
        ) sub
    """)

    # 5. Ensure campaigns without any conversation still get an empty world_state row.
    op.execute("""
        INSERT INTO world_state (campaign_id, location, world_clock, created_at, updated_at)
        SELECT c.id, '', '', now(), now()
        FROM campaigns c
        WHERE NOT EXISTS (
            SELECT 1 FROM world_state ws WHERE ws.campaign_id = c.id
        )
    """)

    # 6. Drop the now-unused conversation columns.
    op.drop_column('conversations', 'location')
    op.drop_column('conversations', 'story_background')
    op.drop_column('conversations', 'world_clock')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('conversations', sa.Column('location', sa.String(), nullable=True))
    op.add_column('conversations', sa.Column('story_background', sa.Text(), nullable=True))
    op.add_column('conversations', sa.Column('world_clock', sa.String(), nullable=True, server_default=''))

    # Restore a flat per-conversation value from the campaign-level rows.
    op.execute("""
        UPDATE conversations conv
        SET location = ws.location,
            world_clock = ws.world_clock,
            story_background = camp.story_background
        FROM world_state ws, campaigns camp
        WHERE conv.campaign_id = ws.campaign_id
          AND conv.campaign_id = camp.id
    """)

    op.drop_index(op.f('ix_world_state_campaign_id'), table_name='world_state')
    op.drop_table('world_state')
    op.drop_column('campaigns', 'story_background')
