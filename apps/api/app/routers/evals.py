"""Evaluation results.

The API serves artifacts the offline harness produced; it never runs an evaluation and
never opens a label file. Only the authored golden report is committed — the external
benchmark's report stays local, because it is derived from a corpus we may not
redistribute.
"""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.schemas import EvalReportResponse

router = APIRouter(tags=["evals"])

GOLDEN_REPORT_FILE = "golden-deterministic-v1.json"


@router.get("/evals/triage", response_model=EvalReportResponse)
def get_triage_evaluation(
    settings: Annotated[Settings, Depends(get_settings)],
) -> EvalReportResponse:
    """The most recent committed triage evaluation."""
    path = settings.evals_dir / GOLDEN_REPORT_FILE

    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No triage evaluation artifact found. Generate one with "
                "`uv run python scripts/evaluate_triage.py --suite golden`."
            ),
        )

    try:
        return EvalReportResponse.model_validate(json.loads(path.read_text("utf-8")))
    except (json.JSONDecodeError, ValidationError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Evaluation artifact is unreadable: {error}",
        ) from error
