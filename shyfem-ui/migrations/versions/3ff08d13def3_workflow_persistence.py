"""workflow persistence

Revision ID: 3ff08d13def3
Revises: 25e58be88f8b
Create Date: 2026-04-29 17:17:28.138425

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3ff08d13def3'
down_revision: Union[str, Sequence[str], None] = '25e58be88f8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('workflows',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('template', sa.String(), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'PAUSED', name='workflow_status'), nullable=False),
    sa.Column('steps', sa.JSON(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('workflows', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workflows_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflows_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('workflows', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workflows_user_id'))
        batch_op.drop_index(batch_op.f('ix_workflows_project_id'))

    op.drop_table('workflows')
