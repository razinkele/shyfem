"""lagrangian file_type for lgr

Backfills existing `.lgr` ProjectFile rows from file_type='other' to
'lagrangian' so pages/ibm.py's picker filter file_types=['lagrangian']
sees them. New .lgr inserts (post-Task-1) get the right type at scan
time; this migration only fixes legacy rows.

Revision ID: 379248193d58
Revises: 3ff08d13def3
Create Date: 2026-05-05 16:34:10.896729

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '379248193d58'
down_revision: Union[str, Sequence[str], None] = '3ff08d13def3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite-compatible case-insensitive LIKE via lower(rel_path).
    # Pre-migration audit (Step 2) confirmed all legacy .lgr rows are
    # currently typed 'other'; if the audit found other types, widen
    # the filter or run additional UPDATE statements before this one.
    op.execute(
        "UPDATE project_files SET file_type = 'lagrangian' "
        "WHERE file_type = 'other' AND lower(rel_path) LIKE '%.lgr'"
    )


def downgrade() -> None:
    """Downgrade schema.

    WARNING: this reverts ALL `lagrangian`-typed `.lgr` rows back to
    `'other'`, including any inserted by the new `_infer_file_type`
    branch AFTER Task 1 landed. Only safe in dev with a fresh DB. After
    downgrading you must either re-seed test data or trigger a rescan
    (`FileService.scan_project(...)`) to restore correct classifications;
    otherwise Task 1's `test_infer_file_type_lagrangian_lgr` will
    appear to "regress" because the rows were stomped, not the code.
    """
    op.execute(
        "UPDATE project_files SET file_type = 'other' "
        "WHERE file_type = 'lagrangian' AND lower(rel_path) LIKE '%.lgr'"
    )
