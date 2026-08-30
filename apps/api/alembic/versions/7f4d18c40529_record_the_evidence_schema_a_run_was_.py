"""record the evidence schema a run was given

Revision ID: 7f4d18c40529
Revises: 835a7a194433
Create Date: 2026-08-30 03:03:33.479513

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f4d18c40529'
down_revision: Union[str, Sequence[str], None] = '835a7a194433'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Record which evidence contract each run was given.

    Existing rows default to `evidence-v1` — they were produced before temporal evidence
    existed, and that is a fact about them worth keeping rather than a gap to fill in.
    `temporal_config_version` stays null for those for the same reason.
    """
    op.add_column(
        "investigation_runs",
        sa.Column(
            "evidence_schema_version",
            sa.String(length=32),
            nullable=False,
            server_default="evidence-v1",
        ),
    )
    op.add_column(
        "investigation_runs",
        sa.Column("temporal_config_version", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("investigation_runs", "temporal_config_version")
    op.drop_column("investigation_runs", "evidence_schema_version")
