"""drop worlds and lore_entries tables, remove conversation world_id

Neo4j is now the single source of truth for lore worlds and entries.

Revision ID: 67858868123c
Revises: cb887e709ca7
Create Date: 2026-04-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '67858868123c'
down_revision: Union[str, Sequence[str], None] = 'cb887e709ca7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        'conversations_world_id_fkey', 'conversations', type_='foreignkey',
    )
    op.drop_index('ix_conversations_world_id', table_name='conversations')
    op.drop_column('conversations', 'world_id')

    op.drop_index('ix_lore_entries_world_id', table_name='lore_entries')
    op.drop_table('lore_entries')

    op.drop_index('ix_worlds_name', table_name='worlds')
    op.drop_table('worlds')


def downgrade() -> None:
    op.create_table(
        'worlds',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_worlds_name', 'worlds', ['name'], unique=True)

    op.create_table(
        'lore_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('world_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('ingestion_status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_lore_entries_world_id', 'lore_entries', ['world_id'], unique=False)

    op.add_column('conversations', sa.Column('world_id', sa.Integer(), nullable=True))
    op.create_index('ix_conversations_world_id', 'conversations', ['world_id'], unique=False)
    op.create_foreign_key(
        'conversations_world_id_fkey', 'conversations', 'worlds',
        ['world_id'], ['id'],
    )
