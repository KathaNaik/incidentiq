"""Correlation review endpoints.

The operator is resolving an operational ambiguity — whether two reports describe one
incident. That the system also keeps the answer as supervision is a consequence, not the
purpose, and no surface here says otherwise.

No model is called on any of these paths.
"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.dependencies import ReviewServiceDep
from app.review import (
    DEMO_OPERATOR,
    CorrelationReview,
    DecisionRequest,
    DecisionResult,
    ReviewConflict,
    ReviewError,
)

router = APIRouter(tags=["reviews"])


class ActorNote(BaseModel):
    """Attached to decisions so the prototype's limits stay visible."""

    model_config = ConfigDict(frozen=True)

    actor: str = DEMO_OPERATOR
    note: str = (
        "This prototype has no authentication. Every review decision is recorded "
        "against a fixed demo operator rather than a signed-in user."
    )


class DecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    result: DecisionResult
    actor: ActorNote = ActorNote()


@router.get("/correlation-reviews", response_model=list[CorrelationReview])
def list_reviews(
    reviews: ReviewServiceDep, pending_only: bool = True
) -> list[CorrelationReview]:
    """The review queue, oldest first.

    Staleness is evaluated on read, so a queue never offers a question whose answer would
    be applied to a candidate that has since changed.
    """
    return reviews.pending() if pending_only else reviews.all_reviews()


@router.get("/correlation-reviews/{review_id}", response_model=CorrelationReview)
def get_review(review_id: str, reviews: ReviewServiceDep) -> CorrelationReview:
    review = reviews.get(review_id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown review: {review_id}"
        )
    return review


@router.post("/correlation-reviews/{review_id}/confirm", response_model=DecisionResponse)
def confirm(
    review_id: str,
    reviews: ReviewServiceDep,
    request: Annotated[DecisionRequest, Body()] = DecisionRequest(),
) -> DecisionResponse:
    """Records that the ticket belongs to this candidate, and attaches it.

    409 when the review was already decided the other way, when the candidate changed
    after the review was created, or when the ticket is attached elsewhere — a click
    against stale information must not silently reshape current state.
    """
    return DecisionResponse(result=_decide(reviews.confirm, review_id, request))


@router.post("/correlation-reviews/{review_id}/reject", response_model=DecisionResponse)
def reject(
    review_id: str,
    reviews: ReviewServiceDep,
    request: Annotated[DecisionRequest, Body()] = DecisionRequest(),
) -> DecisionResponse:
    """Records that the ticket does not belong to *this* candidate.

    Not that it belongs to nothing: other pending reviews for the same ticket stay open.
    """
    return DecisionResponse(result=_decide(reviews.reject, review_id, request))


def _decide(action, review_id: str, request: DecisionRequest) -> DecisionResult:
    try:
        return action(review_id, reason=request.reason, note=request.note)
    except ReviewConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    except ReviewError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
