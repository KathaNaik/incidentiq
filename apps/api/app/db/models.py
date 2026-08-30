"""The durable schema.

Two shapes appear here deliberately.

**Workflow state is relational.** Actions, approvals, executions and audit events have
real relationships, real constraints, and questions worth asking across them — "which
run produced this rollback", "has this action already executed". Foreign keys and unique
constraints do work here that application code would otherwise have to be trusted to do.

**Evidence and model output are JSONB.** An evidence snapshot is a record of what the
model was shown, and its value is that it is *exactly* that. Shredding it across ten
tables would make it queryable at the cost of making it reconstructible, and
reconstruction is the requirement. The structured result is stored the same way, and
validated back through the same Pydantic models on the way out.
"""

from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Float,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# BAAI/bge-small-en-v1.5. Unchanged in this milestone — the column is sized for it, and
# `embedding_model` on every row records which model actually produced the vector so a
# future change cannot silently reinterpret old ones.
EMBEDDING_DIMENSIONS = 384

# JSONB on PostgreSQL, plain JSON elsewhere, so the models stay importable without a
# database for the unit tests that only need the types.
JSONColumn = JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class InvestigationRunRow(Base):
    """One exact invocation of one investigator against one evidence snapshot.

    Immutable once terminal. Nothing in the application updates a succeeded or failed
    run — a re-investigation inserts a new row, so "what did investigator-v2 see when it
    recommended this rollback" stays answerable after the world has moved on.
    """

    __tablename__ = "investigation_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # Which investigator, exactly. Version and prompt are separate because they can move
    # independently, and a metric attributed to the wrong one is a metric about nothing.
    investigator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Exactly what the model was shown. Never reconstructed from current fixtures.
    evidence_snapshot: Mapped[list] = mapped_column(JSONColumn, nullable=False)
    # Which evidence contract this run was given. Runs recorded before M14 are
    # evidence-v1 and stay that way: temporal evidence is never backfilled onto a
    # historical run, because then nobody could tell why two runs differed.
    evidence_schema_version: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="evidence-v1"
    )
    # The window and threshold configuration the temporal derivation used. A stored run
    # must be interpretable with the constants it was produced under, not whatever the
    # code says today.
    temporal_config_version: Mapped[str | None] = mapped_column(String(32))
    # The validated InvestigationOutput. Null while pending/running, and on failure.
    structured_result: Mapped[dict | None] = mapped_column(JSONColumn)

    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    # Count only. The reasoning content itself is never requested, returned or stored.
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)

    failure_type: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(Text)

    actions: Mapped[list["ActionRow"]] = relationship(back_populates="investigation_run")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_investigation_runs_status",
        ),
        # Newest-first history for one incident is the only listing the product does.
        Index("ix_investigation_runs_incident_created", "incident_id", "created_at"),
    )


class ActionRow(Base):
    """A proposed remediation, and the policy decision that gated it."""

    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # The exact run whose recommendation this action came from. Not nullable in normal
    # operation and never repointed: re-investigating an incident later must not silently
    # re-attribute an action a human already approved to a run that did not propose it.
    investigation_run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("investigation_runs.id", ondelete="RESTRICT"), index=True
    )

    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # Derived by policy from cited evidence, never taken from the model.
    target: Mapped[dict] = mapped_column(JSONColumn, nullable=False)

    # The model said one thing about risk; policy assigned another. Both kept, because
    # the gap between them is the point.
    model_stated_risk: Mapped[str | None] = mapped_column(String(16))
    effective_risk: Mapped[str] = mapped_column(String(16), nullable=False)

    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_decision: Mapped[dict] = mapped_column(JSONColumn, nullable=False)

    recommendation_summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_evidence_ids: Mapped[list] = mapped_column(JSONColumn, nullable=False)
    validated_evidence_ids: Mapped[list] = mapped_column(JSONColumn, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    investigation_run: Mapped["InvestigationRunRow | None"] = relationship(
        back_populates="actions"
    )
    approval: Mapped["ApprovalRow | None"] = relationship(
        back_populates="action", uselist=False, cascade="all, delete-orphan"
    )
    execution: Mapped["ExecutionResultRow | None"] = relationship(
        back_populates="action", uselist=False, cascade="all, delete-orphan"
    )


class ApprovalRow(Base):
    """One human decision per action.

    The unique constraint on `action_id` is the durable form of "approval is not a thing
    that accumulates". A second approve is either a no-op or an error; it is never a
    second row that leaves the action's history ambiguous.
    """

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("actions.id", ondelete="CASCADE"), nullable=False
    )
    approved: Mapped[bool] = mapped_column(nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    reason: Mapped[str | None] = mapped_column(Text)

    action: Mapped["ActionRow"] = relationship(back_populates="approval")

    __table_args__ = (
        UniqueConstraint("action_id", name="uq_approvals_action"),
        # An approval is a human act. The database says so, so that a future code path
        # cannot quietly record the system approving its own proposal.
        CheckConstraint("actor_type = 'human'", name="ck_approvals_actor_is_human"),
    )


class ExecutionResultRow(Base):
    """The simulated execution, once.

    The unique constraint on `action_id` is what makes idempotency durable rather than
    conventional: a second execution cannot insert a second result, whatever the calling
    code believes. Restarting the API changes nothing about that.
    """

    __tablename__ = "execution_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("actions.id", ondelete="CASCADE"), nullable=False
    )
    simulated: Mapped[bool] = mapped_column(nullable=False, default=True)
    succeeded: Mapped[bool] = mapped_column(nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[list] = mapped_column(JSONColumn, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    action: Mapped["ActionRow"] = relationship(back_populates="execution")

    __table_args__ = (
        UniqueConstraint("action_id", name="uq_execution_results_action"),
        CheckConstraint("simulated", name="ck_execution_results_simulated_only"),
    )


class AuditEventRow(Base):
    """Append-only, and ordered deterministically.

    `sequence` exists because timestamps are not a reliable tie-break: several events in
    one transaction can share a microsecond, and an audit trail that reorders between
    reads is not an audit trail. Ordering is always (occurred_at, sequence).
    """

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # A database-generated identity, not an application counter: the ordering has to be
    # correct across processes, and `autoincrement` does nothing on a non-primary-key
    # column — it silently inserted NULLs until a test caught it.
    sequence: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), nullable=False, unique=True
    )

    incident_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # Deliberately *not* foreign keys.
    #
    # An audit trail must be able to outlive and precede what it describes. The first
    # event recorded for an action is "the model recommended this", written before the
    # system decides to create an action at all — a foreign key forbids that ordering and
    # would force the log to be written after the fact, which is the opposite of what an
    # audit log is for. Indexed for lookup; referential integrity is not the goal here.
    action_id: Mapped[str | None] = mapped_column(String(64), index=True)
    investigation_run_id: Mapped[str | None] = mapped_column(String(64), index=True)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    details: Mapped[dict] = mapped_column(JSONColumn, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('model', 'system', 'human')",
            name="ck_audit_events_actor_type",
        ),
        # The model recommends; it never executes. Enforced in the database so the
        # boundary survives a future refactor of the service layer.
        CheckConstraint(
            "NOT (actor_type = 'model' AND event_type LIKE 'execution%')",
            name="ck_audit_events_model_never_executes",
        ),
        Index("ix_audit_events_order", "occurred_at", "sequence"),
    )


class HistoricalIncidentRow(Base):
    """A resolved past incident, and its symptom vector.

    `root_cause` and `resolution_steps` are columns like any other — but nothing that
    builds indexed text or a query ever reads them. That boundary lives in
    `app.retrieval.text`, and the import writes `index_text` into `indexed_text` so what
    was embedded is inspectable rather than a claim.
    """

    __tablename__ = "historical_incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    services: Mapped[list[str]] = mapped_column(
        ARRAY(Text).with_variant(JSON(), "sqlite"), nullable=False, default=list
    )
    observed_errors: Mapped[list[str]] = mapped_column(
        ARRAY(Text).with_variant(JSON(), "sqlite"), nullable=False, default=list
    )
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Read only after a match, never indexed and never in a query.
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_steps: Mapped[list] = mapped_column(JSONColumn, nullable=False, default=list)

    # Exactly the text that was embedded, so the leakage boundary is auditable in situ.
    indexed_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    embedding_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)

    # Normalized by the same Python function the in-memory index used, so the reranking
    # terms mean the same thing in SQL as they did in the loop they replaced.
    service_tokens: Mapped[list[str]] = mapped_column(
        ARRAY(Text).with_variant(JSON(), "sqlite"), nullable=False, default=list
    )
    error_tokens: Mapped[list[str]] = mapped_column(
        ARRAY(Text).with_variant(JSON(), "sqlite"), nullable=False, default=list
    )

    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    __table_args__ = (
        UniqueConstraint("provenance", "source_record_id", name="uq_historical_source"),
    )


# --- runtime intake ---------------------------------------------------------------------


class TicketRow(Base):
    """A report, as the running system holds it.

    Tickets moved into PostgreSQL in M15 so a previously unseen one can arrive through the
    API and change live incident state. The authored Northstar tickets are seeded into the
    same table rather than kept in a parallel fixture universe — one representation, with
    `source` preserving where each came from.

    Two timestamps, because they answer different questions. `created_at` is when the
    reporter says the problem was observed and is what correlation and the M14 chronology
    use. `received_at` is when IncidentIQ was told, and is never allowed to redefine
    incident onset — a report filed an hour late describes an hour-old event.
    """

    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # The caller's key, and the idempotency key. Unique so a retried submission cannot
    # create a second ticket — enforced by the database rather than by a prior read.
    external_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reported_by: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    # What the reporter claimed, kept separate from what triage predicted. Conflating them
    # would make it impossible to tell a stated service from an inferred one.
    reported_service_id: Mapped[str | None] = mapped_column(String(64))
    service_id: Mapped[str | None] = mapped_column(String(64), index=True)
    priority: Mapped[str | None] = mapped_column(String(16))
    issue_type: Mapped[str | None] = mapped_column(String(64))
    triage_version: Mapped[str | None] = mapped_column(String(64))
    # The signals behind the prediction, so a triage decision stays explicable.
    triage_signals: Mapped[dict | None] = mapped_column(JSONColumn)

    # Null is a real state: a ticket that matched nothing is uncorrelated, not broken.
    candidate_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("candidate_incidents.id", ondelete="SET NULL"), index=True
    )

    candidate: Mapped["CandidateIncidentRow | None"] = relationship(
        back_populates="tickets"
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('api', 'northstar-authored', 'imported', 'external-eval')",
            name="ck_tickets_source",
        ),
        Index("ix_tickets_created", "created_at"),
    )


class CandidateIncidentRow(Base):
    """A grouping the correlation baseline proposed, persisted so it can grow.

    Metadata is recomputed from members on every change rather than incremented, so a
    count and its membership cannot drift apart.
    """

    __tablename__ = "candidate_incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    correlation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    title: Mapped[str] = mapped_column(Text, nullable=False)
    service_id: Mapped[str | None] = mapped_column(String(64), index=True)
    issue_type: Mapped[str | None] = mapped_column(String(64))

    # Derived from members. first/last_seen are reporter times, not receive times.
    ticket_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    distinct_reporters: Mapped[int | None] = mapped_column(Integer)

    signals: Mapped[dict] = mapped_column(JSONColumn, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    tickets: Mapped[list["TicketRow"]] = relationship(back_populates="candidate")

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'stale', 'resolved')", name="ck_candidates_status"
        ),
    )


class CorrelationDecisionRow(Base):
    """Why one ticket went where it did, at the moment it arrived.

    Recorded rather than recomputed. Thresholds and correlation versions will change, and
    a later change must not silently rewrite the reason a ticket was attached last Tuesday
    — "why did IncidentIQ group this?" is a question about the past.
    """

    __tablename__ = "correlation_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[str | None] = mapped_column(String(64), index=True)

    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    triage_version: Mapped[str | None] = mapped_column(String(64))

    score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str | None] = mapped_column(String(16))
    created_new_candidate: Mapped[bool] = mapped_column(nullable=False, default=False)

    supporting_signals: Mapped[list] = mapped_column(JSONColumn, nullable=False, default=list)
    conflicting_signals: Mapped[list] = mapped_column(JSONColumn, nullable=False, default=list)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Runners-up worth keeping: enough to explain an ambiguous call without storing a row
    # per rejected candidate.
    alternatives: Mapped[list] = mapped_column(JSONColumn, nullable=False, default=list)

    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('attached', 'created_candidate', 'uncorrelated', "
            "'ambiguous', 'failed')",
            name="ck_correlation_decisions_outcome",
        ),
    )
