"""audit events do not depend on what they audit

Revision ID: 835a7a194433
Revises: 542c908d7e8f
Create Date: 2026-08-29 18:22:20.155567

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '835a7a194433'
down_revision: Union[str, Sequence[str], None] = '542c908d7e8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the audit trail's foreign keys.

    The first event for an action is `recommendation_received` — the model recommended
    something — and it is written before the system decides to create an action. A
    foreign key makes that insert fail, which would force the log to be written after the
    decision it records. An audit trail that can only describe things that already exist
    is not an audit trail.

    The columns and their indexes stay: lookup by action or run still works, and the demo
    reset deletes audit rows explicitly rather than relying on a cascade.
    """
    op.drop_constraint("audit_events_action_id_fkey", "audit_events", type_="foreignkey")
    op.drop_constraint(
        "audit_events_investigation_run_id_fkey", "audit_events", type_="foreignkey"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.create_foreign_key(
        "audit_events_action_id_fkey", "audit_events", "actions",
        ["action_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "audit_events_investigation_run_id_fkey", "audit_events", "investigation_runs",
        ["investigation_run_id"], ["id"], ondelete="SET NULL",
    )
