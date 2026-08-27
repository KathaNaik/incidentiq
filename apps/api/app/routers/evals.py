"""Evaluation results.

The API serves artifacts the offline harness produced; it never runs an evaluation and
never opens a label file. Only the authored golden report is committed — the external
benchmark's report stays local, because it is derived from a corpus we may not
redistribute.
"""

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.schemas import EvalReportResponse, VersionComparisonResponse

router = APIRouter(tags=["evals"])

GOLDEN_REPORT_FILE = "golden-deterministic-v1.json"
CORRELATION_REPORTS = {
    "deterministic": "golden-deterministic-correlation-v1.json",
    "semantic": "golden-semantic-correlation-v1.json",
}
COMPARISON_FILE = "comparison-semantic-correlation-v1.json"


@router.get("/evals/triage", response_model=EvalReportResponse)
def get_triage_evaluation(
    settings: Annotated[Settings, Depends(get_settings)],
) -> EvalReportResponse:
    """The most recent committed triage evaluation."""
    return _read(settings.evals_dir / GOLDEN_REPORT_FILE, "triage")


@router.get("/evals/correlation", response_model=EvalReportResponse)
def get_correlation_evaluation(
    settings: Annotated[Settings, Depends(get_settings)],
    version: Annotated[
        Literal["deterministic", "semantic"], Query(description="correlation version")
    ] = "deterministic",
) -> EvalReportResponse:
    """The committed correlation evaluation for one version."""
    return _read(
        settings.correlation_evals_dir / CORRELATION_REPORTS[version], "correlation"
    )


@router.get("/evals/correlation/comparison", response_model=VersionComparisonResponse)
def get_correlation_comparison(
    settings: Annotated[Settings, Depends(get_settings)],
) -> VersionComparisonResponse:
    """Deterministic versus semantic on identical inputs, with per-slice examples."""
    path = settings.correlation_evals_dir / COMPARISON_FILE
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No correlation comparison artifact found. Generate one with "
                "`uv run --group semantic python scripts/evaluate_correlation.py "
                "--suite golden --mode both`."
            ),
        )
    try:
        return VersionComparisonResponse.model_validate(
            json.loads(path.read_text("utf-8"))
        )
    except (json.JSONDecodeError, ValidationError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Comparison artifact is unreadable: {error}",
        ) from error


def _read(path, suite: str) -> EvalReportResponse:
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No {suite} evaluation artifact found. Generate one with "
                f"`uv run python scripts/evaluate_{suite}.py --suite golden`."
            ),
        )

    try:
        return EvalReportResponse.model_validate(json.loads(path.read_text("utf-8")))
    except (json.JSONDecodeError, ValidationError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Evaluation artifact is unreadable: {error}",
        ) from error
