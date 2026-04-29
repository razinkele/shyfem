"""unique project_file rel_path

Revision ID: 25e58be88f8b
Revises: f423af2c2f44
Create Date: 2026-04-29 17:12:42.426517

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25e58be88f8b'
down_revision: Union[str, Sequence[str], None] = 'f423af2c2f44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('project_files', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_project_file_path', ['project_id', 'rel_path'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('project_files', schema=None) as batch_op:
        batch_op.drop_constraint('uq_project_file_path', type_='unique')
