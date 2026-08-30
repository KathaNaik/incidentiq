"""record hybrid correlation staging

Revision ID: 153d35e0263b
Revises: cdcf60677681
Create Date: 2026-08-30 04:09:15.535672

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '153d35e0263b'
down_revision: Union[str, Sequence[str], None] = 'cdcf60677681'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Record how a hybrid decision was reached, not just what it decided.

    Nullable throughout: decisions recorded before M16 were made by a single strategy and
    had no fallback stage. Backfilling empty structures onto them would imply a fallback
    was considered and declined, which is not what happened.
    """
    op.add_column("correlation_decisions", sa.Column("strategy", sa.String(length=64), nullable=True))
    op.add_column(
        "correlation_decisions",
        sa.Column("deterministic_stage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "correlation_decisions",
        sa.Column("fallback_stage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "correlation_decisions",
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    for column in ("embedding_model", "fallback_stage", "deterministic_stage", "strategy"):
        op.drop_column("correlation_decisions", column)
