"""add feedbacks table

Revision ID: ccde037a5855
Revises: 0f5d3b086cf0
Create Date: 2026-06-14 10:06:12.891559

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "ccde037a5855"
down_revision: Union[str, Sequence[str], None] = "0f5d3b086cf0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "feedbacks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("feedback_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("page", sa.String(length=64), nullable=True),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'new'"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedbacks_created_at", "feedbacks", ["created_at"])
    op.create_index("ix_feedbacks_feedback_type", "feedbacks", ["feedback_type"])
    op.create_index("ix_feedbacks_status", "feedbacks", ["status"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_feedbacks_status", "feedbacks")
    op.drop_index("ix_feedbacks_feedback_type", "feedbacks")
    op.drop_index("ix_feedbacks_created_at", "feedbacks")
    op.drop_table("feedbacks")
