"""operator correlation review

Revision ID: 51e319090169
Revises: 153d35e0263b
Create Date: 2026-08-30 18:05:38.284376

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '51e319090169'
down_revision: Union[str, Sequence[str], None] = '153d35e0263b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Capture ambiguous grouping decisions with the state they were made against.

    JSONB for the four snapshots because they are immutable evidence payloads, the same
    shape as the M13 investigation snapshot: their value is being exactly what was shown,
    not being queryable field by field.
    """
    op.create_table(
        "correlation_reviews",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("ticket_id", sa.String(length=64), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("decision_reason", sa.String(length=64), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("correlation_version", sa.String(length=64), nullable=False),
        sa.Column("review_policy_version", sa.String(length=64), nullable=False),
        sa.Column("feature_schema", sa.String(length=64), nullable=False),
        sa.Column("candidate_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("ticket_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("candidate_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correlation_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("feature_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resulting_membership", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected', 'stale')",
            name="ck_correlation_reviews_status",
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN "
            "('confirm_same_incident', 'reject_different_incident')",
            name="ck_correlation_reviews_decision",
        ),
        sa.CheckConstraint(
            "(status IN ('pending', 'stale') AND decision IS NULL) OR "
            "(status IN ('confirmed', 'rejected') AND decision IS NOT NULL "
            " AND decided_at IS NOT NULL)",
            name="ck_correlation_reviews_decision_complete",
        ),
        sa.UniqueConstraint(
            "ticket_id", "candidate_id", "candidate_fingerprint",
            name="uq_correlation_reviews_snapshot",
        ),
    )
    op.create_index("ix_correlation_reviews_ticket_id", "correlation_reviews", ["ticket_id"])
    op.create_index("ix_correlation_reviews_candidate_id", "correlation_reviews", ["candidate_id"])
    op.create_index("ix_correlation_reviews_status", "correlation_reviews", ["status"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("correlation_reviews")
