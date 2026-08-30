"""one active investigation per incident

Revision ID: 2d1e67318f0a
Revises: d45627f8a057
Create Date: 2026-08-29 18:13:35.965207

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d1e67318f0a'
down_revision: Union[str, Sequence[str], None] = 'd45627f8a057'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """One in-flight investigation per incident, enforced by the database.

    A check-then-insert in application code cannot hold across two processes: both
    requests read "no active run" before either commits, and the incident gets two
    concurrent model calls. A partial unique index makes the second insert fail instead,
    and the caller returns the run that already exists.
    """
    op.execute(
        """
        CREATE UNIQUE INDEX uq_investigation_runs_one_active
        ON investigation_runs (incident_id)
        WHERE status IN ('pending', 'running')
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS uq_investigation_runs_one_active")
