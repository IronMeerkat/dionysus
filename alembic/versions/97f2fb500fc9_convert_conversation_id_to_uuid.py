"""convert_message_id_to_uuid

Revision ID: 97f2fb500fc9
Revises: 6e3fadd66a9c
Create Date: 2026-02-21 11:11:45.197372

PostgreSQL cannot cast Integer to UUID directly. We add a new UUID column,
populate it with gen_random_uuid(), then swap.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '97f2fb500fc9'
down_revision: Union[str, Sequence[str], None] = '6e3fadd66a9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: messages.id Integer -> UUID."""
    conn = op.get_bind()

    # 1. Add new UUID column
    op.add_column('messages', sa.Column('id_new', UUID(as_uuid=True), nullable=True))

    # 2. Populate with gen_random_uuid() for each row
    conn.execute(sa.text("UPDATE messages SET id_new = gen_random_uuid()"))

    # 3. Drop PK, drop old column, rename new column
    op.drop_constraint('messages_pkey', 'messages', type_='primary')
    op.drop_column('messages', 'id')
    op.alter_column(
        'messages',
        'id_new',
        new_column_name='id',
        nullable=False,
    )

    # 4. Add primary key
    op.create_primary_key('messages_pkey', 'messages', ['id'])


def downgrade() -> None:
    """Downgrade schema: messages.id UUID -> Integer."""
    conn = op.get_bind()

    # 1. Add new integer column
    op.add_column('messages', sa.Column('id_new', sa.INTEGER(), nullable=True))

    # 2. Assign sequential integers (order by created_at for consistency)
    conn.execute(sa.text("""
        WITH numbered AS (
            SELECT id, row_number() OVER (ORDER BY created_at) AS rn
            FROM messages
        )
        UPDATE messages m
        SET id_new = numbered.rn
        FROM numbered
        WHERE m.id = numbered.id
    """))

    # 3. Drop PK, drop old column, rename new column
    op.drop_constraint('messages_pkey', 'messages', type_='primary')
    op.drop_column('messages', 'id')
    op.alter_column(
        'messages',
        'id_new',
        new_column_name='id',
        nullable=False,
    )

    # 4. Add primary key
    op.create_primary_key('messages_pkey', 'messages', ['id'])
