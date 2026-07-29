"""add campaign mechanics table

Negotiated custom mechanics documents for a campaign (title + self-contained
markdown content), written by the campaign-negotiation agent and read by the
DM at play time. Structured per-character roll mechanics live in
``character_status_effects``; this table holds the free-form systems
(engines, tracks, ladders, levers) no structured field can express.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-29 19:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'campaign_mechanics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('campaign_id', 'title', name='uq_campaign_mechanics_campaign_title'),
    )
    op.create_index(op.f('ix_campaign_mechanics_campaign_id'), 'campaign_mechanics', ['campaign_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_campaign_mechanics_campaign_id'), table_name='campaign_mechanics')
    op.drop_table('campaign_mechanics')
