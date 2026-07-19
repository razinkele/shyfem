"""project_permissions fk cascade

F24: project_permissions.project_id/user_id were created (8590185869a6) as
bare, unnamed ``ForeignKeyConstraint``s with no ``ondelete``. Deleting a
project or user that still has permission rows is rejected by SQLite's FK
enforcement (PRAGMA foreign_keys=ON, db/base.py), unlike grids/simulations/
files which cascade via the ORM. This adds ON DELETE CASCADE to both FKs so
deleting the parent project or user removes its permission rows.

SQLite has no ALTER TABLE ... ALTER CONSTRAINT, so batch mode rebuilds the
table. The original FKs are unnamed, so reflection reports ``name=None``;
a naming_convention is supplied to the batch op purely so the reflected
constraints get deterministic names that drop_constraint() can target -- it
does not change the schema.

Revision ID: 85f9efff4f5e
Revises: ccde037a5855
Create Date: 2026-07-19 12:20:36.549943

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '85f9efff4f5e'
down_revision: Union[str, Sequence[str], None] = 'ccde037a5855'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Deterministic names for the (originally unnamed) FK constraints, applied to
# the batch op's reflected copy of the table so drop_constraint()/
# create_foreign_key() can address them by name.
_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
}
_PROJECT_FK = "fk_project_permissions_project_id_projects"
_USER_FK = "fk_project_permissions_user_id_users"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table(
        "project_permissions", schema=None, naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(_PROJECT_FK, type_="foreignkey")
        batch_op.drop_constraint(_USER_FK, type_="foreignkey")
        batch_op.create_foreign_key(
            _PROJECT_FK, "projects", ["project_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_foreign_key(
            _USER_FK, "users", ["user_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table(
        "project_permissions", schema=None, naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(_PROJECT_FK, type_="foreignkey")
        batch_op.drop_constraint(_USER_FK, type_="foreignkey")
        batch_op.create_foreign_key(
            _PROJECT_FK, "projects", ["project_id"], ["id"]
        )
        batch_op.create_foreign_key(_USER_FK, "users", ["user_id"], ["id"])
