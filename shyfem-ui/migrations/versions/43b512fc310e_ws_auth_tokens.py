"""ws_auth_tokens

Revision ID: 43b512fc310e
Revises: 379248193d58
Create Date: 2026-05-28 10:00:18.445936

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '43b512fc310e'
down_revision: Union[str, Sequence[str], None] = '379248193d58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'ws_auth_tokens',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('token', sa.String(length=255), nullable=False),
        sa.Column('session_token', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('ws_auth_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ws_auth_tokens_session_token'), ['session_token'], unique=False)
        batch_op.create_index(batch_op.f('ix_ws_auth_tokens_token'), ['token'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ws_auth_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ws_auth_tokens_token'))
        batch_op.drop_index(batch_op.f('ix_ws_auth_tokens_session_token'))
    op.drop_table('ws_auth_tokens')
