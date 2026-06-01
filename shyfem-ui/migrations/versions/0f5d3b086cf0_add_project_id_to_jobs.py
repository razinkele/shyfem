"""add project_id to jobs

Revision ID: 0f5d3b086cf0
Revises: 43b512fc310e
Create Date: 2026-06-01 17:42:03.469004

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0f5d3b086cf0"
down_revision: Union[str, Sequence[str], None] = "43b512fc310e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add jobs.project_id (nullable FK to projects) + index.

    Basis for cancel authorization (owner / admin / project-editor). Existing
    rows keep project_id NULL; their cancel authz then falls back to owner /
    admin only, which is correct for pre-migration jobs.
    """
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_jobs_project_id_projects", "projects", ["project_id"], ["id"]
        )
        batch_op.create_index(batch_op.f("ix_jobs_project_id"), ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_jobs_project_id"))
        batch_op.drop_constraint("fk_jobs_project_id_projects", type_="foreignkey")
        batch_op.drop_column("project_id")
