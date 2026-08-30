"""Features for the pairwise incident-identity decision.

M17 established that whole-ticket cosine measures *topical resemblance*: two tickets about
authentication are close in embedding space whether they describe one failure or two. This
module describes the decision the product actually makes instead —

    does this arriving ticket belong to this candidate, right now?

— from signals the deterministic engine already computes. That is deliberate. The
deterministic pairwise scorer knows about service agreement, issue-type contradiction,
shared identifiers, time decay and lexical overlap; what it does not do is *weigh* them
against labelled outcomes. Learning the weights is the experiment.

**Leakage controls.** Every feature is a function of (arriving ticket, candidate members
that already existed). Nothing reads a root cause, a resolution, an `event_id`, a
benchmark label, an investigation result, or a ticket that arrived later. The candidate is
always reconstructed as it stood *before* the arrival — a test asserts it, because this is
the one mistake that would make every number here meaningless.

**Named, ordered, versioned.** Features are a dict keyed by name and serialised through
`FEATURE_NAMES`, so a reordering cannot silently feed the model a permuted vector.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.correlation.models import Component, CorrelationTicket, Direction
from app.correlation.pairwise import Corpus, TicketFeatures, prepare, score_pair
from app.correlation.rules import CANDIDATE_IDLE_MINUTES

FEATURE_SCHEMA_VERSION = "pairwise-features-v1"

# Order is part of the contract. The model artifact records this list, and loading
# validates against it rather than trusting the caller to build the vector correctly.
FEATURE_NAMES: tuple[str, ...] = (
    # --- service -------------------------------------------------------------------
    "service_same",
    "service_conflict",
    "service_unknown",
    # --- time ----------------------------------------------------------------------
    "minutes_to_nearest_member",
    "minutes_to_first_member",
    "time_score_nearest",
    "within_active_window",
    # --- issue semantics -------------------------------------------------------------
    "issue_same",
    "issue_conflict",
    "issue_unknown",
    # --- identifiers -----------------------------------------------------------------
    "shared_identifier_count",
    "identifier_conflict",
    "shared_symptom_count",
    # --- lexical ---------------------------------------------------------------------
    "lexical_min",
    "lexical_mean",
    "lexical_max",
    # --- candidate cohesion ------------------------------------------------------------
    "candidate_size",
    "content_min",
    "content_mean",
    "content_max",
    "blended_min",
    "blended_mean",
    "blended_max",
    "members_agreeing",
    "members_conflicting",
    "fraction_members_agreeing",
)


@dataclass(frozen=True)
class PairwiseExample:
    """One runtime decision, as the model sees it.

    `label` is present only for training data and is never a feature — the separation is
    structural, not a convention someone has to remember.
    """

    features: dict[str, float]
    label: int | None = None
    group: str | None = None
    """The incident/event identity. Used for grouped splitting; never a feature."""

    arriving_id: str = ""
    candidate_id: str = ""

    def vector(self) -> list[float]:
        return [float(self.features[name]) for name in FEATURE_NAMES]


def _component(score, component: Component) -> tuple[float, Direction]:
    for signal in score.signals:
        if signal.component is component:
            return signal.score, signal.direction
    return 0.0, Direction.NEUTRAL


def _identifier_counts(
    arriving: TicketFeatures, members: Sequence[TicketFeatures]
) -> tuple[int, int, int]:
    """Shared identifiers, conflicting error codes, shared symptoms.

    Identifier *conflict* is counted the way M16's hybrid gate defines it — both sides
    name an error code and none is shared. The deterministic baseline is silent about
    this, and it is the single most decisive negative signal in the authored set.
    """
    incoming_codes = {
        value for value in arriving.identifiers if value.startswith("error_code:")
    }
    shared = conflicts = symptoms = 0
    for member in members:
        shared += len(arriving.identifiers & member.identifiers)
        symptoms += len(arriving.symptoms & member.symptoms)
        theirs = {
            value for value in member.identifiers if value.startswith("error_code:")
        }
        if incoming_codes and theirs and not (theirs & incoming_codes):
            conflicts += 1
    return shared, conflicts, symptoms


def extract(
    arriving: CorrelationTicket,
    members: Sequence[CorrelationTicket],
    corpus: Corpus | None = None,
) -> dict[str, float]:
    """Features for one (arriving ticket, candidate) decision.

    `members` must be the candidate as it stood *before* this ticket arrived. Passing the
    post-arrival membership would leak the answer into the question.
    """
    if not members:
        raise ValueError("a candidate needs at least one member to score against")

    working = corpus or Corpus()
    if corpus is None:
        # Weights reflect only what has been seen, mirroring the live engine's discipline.
        for ticket in sorted(members, key=lambda t: (t.created_at, t.id)):
            working.observe(prepare(ticket).tokens)

    arriving_features = prepare(arriving)
    member_features = [prepare(member) for member in members]
    scores = [
        score_pair(arriving_features, member, working, None) for member in member_features
    ]

    services = [_component(score, Component.SERVICE) for score in scores]
    issues = [_component(score, Component.ISSUE_TYPE) for score in scores]
    lexical = [_component(score, Component.LEXICAL)[0] for score in scores]

    shared_ids, id_conflicts, shared_symptoms = _identifier_counts(
        arriving_features, member_features
    )

    minutes = [score.minutes_apart for score in scores]
    content = [score.content_score for score in scores]
    blended = [score.score for score in scores]
    time_scores = [score.time_score for score in scores]

    agreeing = sum(
        1
        for score in scores
        if any(
            signal.direction is Direction.SUPPORTING
            and signal.component in (Component.SERVICE, Component.ENTITY, Component.LEXICAL)
            for signal in score.signals
        )
    )
    conflicting = sum(
        1
        for score in scores
        if any(signal.direction is Direction.CONFLICTING for signal in score.signals)
    )

    return {
        "service_same": float(any(score > 0 for score, _ in services)),
        "service_conflict": float(
            any(direction is Direction.CONFLICTING for _, direction in services)
        ),
        "service_unknown": float(all(score == 0 for score, _ in services)),
        "minutes_to_nearest_member": min(minutes),
        "minutes_to_first_member": max(minutes),
        "time_score_nearest": max(time_scores),
        "within_active_window": float(min(minutes) <= CANDIDATE_IDLE_MINUTES),
        "issue_same": float(any(score > 0 for score, _ in issues)),
        "issue_conflict": float(
            any(direction is Direction.CONFLICTING for _, direction in issues)
        ),
        "issue_unknown": float(all(score == 0 for score, _ in issues)),
        "shared_identifier_count": float(shared_ids),
        "identifier_conflict": float(id_conflicts > 0),
        "shared_symptom_count": float(shared_symptoms),
        "lexical_min": min(lexical),
        "lexical_mean": sum(lexical) / len(lexical),
        "lexical_max": max(lexical),
        "candidate_size": float(len(members)),
        "content_min": min(content),
        "content_mean": sum(content) / len(content),
        "content_max": max(content),
        "blended_min": min(blended),
        "blended_mean": sum(blended) / len(blended),
        "blended_max": max(blended),
        "members_agreeing": float(agreeing),
        "members_conflicting": float(conflicting),
        "fraction_members_agreeing": agreeing / len(members),
    }
