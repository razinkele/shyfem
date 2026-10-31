"""hash session tokens

SEC-06: ``auth_sessions.token``, ``ws_auth_tokens.token`` and
``ws_auth_tokens.session_token`` now hold ``sha256(raw).hexdigest()`` instead
of the raw token handed to the browser (see ``auth_service._hash_token``).
The digest is 64 hex characters, so the String(255) columns and their
indexes are unchanged: this is a data-only revision.

Rows written before it hold plaintext tokens, which would never validate
again (the lookup hashes the presented value) and are exactly the readable
secrets this change removes, so they are deleted. Everyone with a live
session simply signs in again. Downgrade deletes them too: a digest cannot
be turned back into the token an older release would look up.

Revision ID: 3b483e11a899
Revises: 85f9efff4f5e
Create Date: 2026-10-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '3b483e11a899'
down_revision: Union[str, Sequence[str], None] = '85f9efff4f5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _purge_tokens() -> None:
    # WS tokens first: they point at sessions (by token, not by FK, but keep
    # the dependent rows going first anyway).
    op.execute("DELETE FROM ws_auth_tokens")
    op.execute("DELETE FROM auth_sessions")


def upgrade() -> None:
    """Purge plaintext session and WS-auth tokens."""
    _purge_tokens()


def downgrade() -> None:
    """Purge hashed tokens: an older release cannot look them up."""
    _purge_tokens()
