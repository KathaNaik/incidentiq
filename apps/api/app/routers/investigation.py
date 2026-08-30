"""AI investigation, as durable runs.

Recommends; never executes. Nothing here approves or performs an action.

The shape changed in M13. An investigation used to happen because a page was rendered,
which meant every reload spent eleven seconds and a set of tokens re-deriving an answer
that could differ from the one the operator was looking at a moment ago. Now:

- **GET reads.** It returns what was stored and never calls a model.
- **POST runs.** One explicit request, one model call, one immutable run.

That split is why the endpoints are resources rather than a verb: `investigations` is a
collection of things that happened, and creating one is a deliberate act.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict

from app.config import Settings, get_settings
from app.correlation import CorrelationTicket, correlate
from app.correlation.models import CandidateIncident
from app.correlation.semantic import default_similarity
from app.db.investigation_store import InvestigationRunStore, StoredRun
from app.dependencies import InvestigationStoreDep, RepositoryDep, RetrievalIndexDep
from app.embeddings import EmbeddingError
from app.investigation import (
    InvestigationResult,
    OpenAIInvestigationModel,
    collect_evidence,
    load_operations,
)
from app.investigation.rules import HISTORICAL_EVIDENCE_K
from app.investigation.service import DEFAULT_PROMPT_VERSION
from app.investigation.tools import ToolError
from app.investigation.workflow import ActiveRunExistsError, run_investigation
from app.routers.correlation import Mode

router = APIRouter(tags=["investigation"])

PROVIDER = "openai"


class InvestigationRunSummary(BaseModel):
    """One run, as the history list shows it.

    Deliberately not the whole row: an operator picking between runs needs when, which
    investigator, and whether it worked — not an evidence snapshot per entry.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    incident_id: str
    status: str
    investigator_version: str
    prompt_version: str
    provider: str
    model: str
    evidence_schema_version: str
    temporal_config_version: str | None
    created_at: str
    completed_at: str | None
    latency_ms: int | None
    evidence_count: int
    abstained: bool | None
    recommended_action: str | None
    failure_type: str | None
    failure_message: str | None


class InvestigationRunDetail(InvestigationRunSummary):
    """One run in full, including the evidence it actually saw.

    `result` is null for a failed or in-flight run — the summary explains why, and the
    caller renders that rather than an empty investigation.
    """

    result: InvestigationResult | None


def _summary(run: StoredRun) -> dict:
    output = run.output
    return {
        "id": run.id,
        "incident_id": run.incident_id,
        "status": run.status,
        "investigator_version": run.investigator_version,
        "prompt_version": run.prompt_version,
        "provider": run.provider,
        "model": run.model,
        "evidence_schema_version": run.evidence_schema_version,
        "temporal_config_version": run.temporal_config_version,
        "created_at": run.created_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "latency_ms": run.latency_ms,
        "evidence_count": len(run.evidence),
        "abstained": output.abstain if output else None,
        "recommended_action": (
            output.remediation.action_type.value
            if output and output.remediation
            else None
        ),
        "failure_type": run.failure_type,
        "failure_message": run.failure_message,
    }


def _detail(run: StoredRun) -> InvestigationRunDetail:
    return InvestigationRunDetail(
        **_summary(run),
        result=run.as_result() if run.succeeded else None,
    )


# --- reads: never call a model ---------------------------------------------------------


@router.get(
    "/incidents/{incident_id}/investigations",
    response_model=list[InvestigationRunSummary],
)
def list_investigations(
    incident_id: str, store: InvestigationStoreDep
) -> list[InvestigationRunSummary]:
    """Run history for one incident, newest first."""
    return [InvestigationRunSummary(**_summary(run)) for run in store.history(incident_id)]


@router.get("/incidents/{incident_id}/investigations/latest")
def latest_investigation(
    incident_id: str,
    store: InvestigationStoreDep,
    repository: RepositoryDep,
    response: Response,
):
    """The investigation an operator should be shown, or 204 if there is not one.

    204 rather than 404: "this incident has not been investigated yet" is a normal state
    of the workflow, not a missing resource, and the UI renders a Run button for it.

    The *latest successful* run, so a failed re-investigation never hides the conclusion
    that is still the best available answer. An in-flight run is reported alongside it so
    the page can show both "here is the current answer" and "a new one is running".
    """
    run = store.latest_successful(incident_id)
    active = store.active(incident_id)

    if run is None and active is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None

    return {
        "current": _detail(run) if run is not None else None,
        "active": InvestigationRunSummary(**_summary(active)) if active else None,
        "staleness": _staleness(run, repository),
    }


def _staleness(run: StoredRun | None, repository) -> dict:
    """Whether reports have arrived since this investigation saw the world.

    Compared by **ticket identity**, not by clock time. A run's snapshot names exactly
    which tickets it was shown; anything on the candidate that is not in that list is
    evidence the run never had. Comparing timestamps instead would call a run stale
    because a back-dated report was filed, or miss one because a new report claims an old
    observation time.

    Reporting staleness never triggers anything. Re-running costs a model call, and that
    stays the operator's decision.
    """
    if run is None or not hasattr(repository, "candidate_tickets"):
        return {"stale": False, "new_ticket_ids": [], "reason": "no investigation yet"}

    seen = {
        item.source_id
        for item in run.evidence
        if item.kind.value == "ticket"
    }
    current = {row.id for row in repository.candidate_tickets(run.incident_id)}
    arrived = sorted(current - seen)

    return {
        "stale": bool(arrived),
        "new_ticket_ids": arrived,
        "reason": (
            f"{len(arrived)} report(s) arrived after this investigation"
            if arrived
            else "this investigation saw every report currently on the incident"
        ),
    }


@router.get("/investigations/{investigation_id}", response_model=InvestigationRunDetail)
def get_investigation(
    investigation_id: str, store: InvestigationStoreDep
) -> InvestigationRunDetail:
    """One exact run, with the evidence snapshot it saw.

    Not current evidence — the snapshot is the record of what the model was actually
    shown, and reconstructing it from today's fixtures would defeat the purpose.
    """
    run = store.get(investigation_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown investigation run: {investigation_id}",
        )
    return _detail(run)


@router.get("/investigations/{investigation_id}/timeline")
def investigation_timeline(investigation_id: str, store: InvestigationStoreDep) -> dict:
    """The chronology of one stored run, recomputed from *its* evidence snapshot.

    A separate endpoint rather than a field on the run because the timeline is a view over
    the snapshot, not another thing stored beside it — deriving it twice from the same
    immutable evidence gives the same answer, and storing it twice would invite the two to
    disagree.

    Recomputed from the snapshot, never from current fixtures: a run from last week must
    show the chronology it actually saw.
    """
    run = store.get(investigation_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown investigation run: {investigation_id}",
        )

    from app.temporal import build_timeline

    timeline = build_timeline(incident_id=run.incident_id, evidence=run.evidence)
    return {
        "investigation_id": run.id,
        "evidence_schema_version": run.evidence_schema_version,
        "timeline": timeline.model_dump(mode="json"),
    }


# --- write: the only path that calls a model -------------------------------------------


@router.post(
    "/incidents/{incident_id}/investigations",
    response_model=InvestigationRunDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_investigation(
    incident_id: str,
    repository: RepositoryDep,
    index: RetrievalIndexDep,
    store: InvestigationStoreDep,
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
    mode: Mode = Mode.DETERMINISTIC,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> InvestigationRunDetail:
    """Runs one investigation and stores it.

    A re-run is the same call again: it creates a new run with a fresh evidence snapshot
    and leaves every earlier run exactly as it was.
    """
    candidate, tickets = _candidate(incident_id, repository, settings, mode)

    try:
        operations = load_operations(settings.fixtures_dir)
    except ToolError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error

    registry = collect_evidence(
        candidate=candidate,
        tickets=tickets,
        operations=operations,
        index=index,
        historical_k=HISTORICAL_EVIDENCE_K,
    )

    summary = (
        f"{candidate.ticket_count} correlated tickets on "
        f"{candidate.service_id or 'an unidentified service'}, first seen "
        f"{candidate.first_seen.isoformat()}, correlation confidence "
        f"{candidate.confidence.value}."
    )

    try:
        run = run_investigation(
            incident_id=incident_id,
            incident_summary=summary,
            registry=registry,
            model=OpenAIInvestigationModel(
                settings.investigation_model, settings.openai_api_key
            ),
            store=store,
            provider=PROVIDER,
            model_name=settings.investigation_model,
            prompt_version=prompt_version,
        )
    except ActiveRunExistsError as error:
        # A duplicate click, or two operators on the same incident. Return what is
        # already running rather than spending a second model call to reach a slightly
        # different answer.
        response.status_code = status.HTTP_409_CONFLICT
        return _detail(error.run)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error

    if run.status == "failed":
        # The run is real and persisted; the investigation did not produce an answer.
        # 502 so the client renders the failure rather than an empty result.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"investigation {run.id} failed ({run.failure_type}): "
                f"{run.failure_message}"
            ),
        )
    return _detail(run)


def _candidate(
    incident_id: str, repository, settings: Settings, mode: Mode
) -> tuple[CandidateIncident, tuple[CorrelationTicket, ...]]:
    tickets = tuple(
        CorrelationTicket(
            id=ticket.id,
            title=ticket.title,
            description=ticket.description,
            created_at=ticket.created_at,
            service_id=ticket.service_id,
            reported_by=ticket.reported_by,
        )
        for ticket in repository.list_tickets()
    )

    try:
        similarity = (
            None
            if mode is Mode.DETERMINISTIC
            else default_similarity(settings.embeddings_cache_dir)
        )
        correlated = correlate(list(tickets), similarity)
    except EmbeddingError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error

    candidate = next(
        (item for item in correlated.candidates if item.id == incident_id), None
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown candidate incident: {incident_id}",
        )
    return candidate, tickets


__all__ = ["InvestigationRunStore", "router"]
