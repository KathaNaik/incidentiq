"""Hybrid correlation: deterministic first, semantic only where it could help.

**This is selective fallback, not semantic correlation on every ticket.** The deterministic
baseline decides almost everything, and embeddings are computed only when it has said
something specific: that a candidate is operationally plausible, and that the thing which
failed was lexical overlap.

Why that distinction matters. Content scoring is

    0.40·service + 0.15·issue + 0.25·lexical + 0.20·entity

Under a genuine paraphrase of the same incident, service still agrees, issue type still
agrees or is unknown, and identifiers contribute nothing because a paraphrase rarely
quotes an error code. The only component that collapses is lexical — the one that measures
*wording* rather than *meaning*. Losing 0.25 of content is usually enough to drop below the
0.50 complete-linkage floor, or below the 0.60 blended bar once time decay is applied.

Semantic similarity is the direct substitute for that one signal, which is why fallback is
gated on the lexical component specifically rather than on a score band. A score band would
also trigger for tickets that are near the threshold for entirely different reasons.

**Eligibility is free.** Every condition below is read from signals `score_pair` already
produced during the deterministic pass, so deciding whether to embed costs nothing.

**Nothing here weakens the guardrails.** Once fallback runs, scoring is exactly
`semantic-correlation-v1` — the same weights, the same complete linkage, the same cohesion
check. Semantic evidence can supply a missing signal; it cannot overrule a service
conflict, a contradictory issue type, or a candidate that has gone quiet.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.correlation.engine import _attaches, correlate
from app.correlation.models import (
    CandidateIncident,
    Component,
    CorrelationResult,
    CorrelationTicket,
    Direction,
    PairwiseScore,
)
from app.correlation.pairwise import Corpus, prepare, score_pair
from app.correlation.rules import (
    PAIRWISE_CORRELATION_VERSION as PAIRWISE_VERSION,
    CANDIDATE_IDLE_MINUTES,
    CONTENT_LINK_MIN,
    HYBRID_CORRELATION_VERSION,
    LEXICAL_WEAKNESS_MAX,
    TIME_LINK_MIN,
)
from app.correlation.semantic import SemanticSimilarity


@dataclass(frozen=True)
class FallbackDecision:
    """Whether semantic evidence could plausibly change this candidate's answer.

    Inspectable on purpose: an operator asking "why did this ticket cost an embedding?"
    — or "why did it not?" — reads these reasons, and every one of them names a
    deterministic signal rather than a threshold.
    """

    candidate_id: str
    eligible: bool
    reasons: tuple[str, ...] = ()
    blocking_reasons: tuple[str, ...] = ()
    deterministic_score: float | None = None

    @property
    def summary(self) -> str:
        return "eligible" if self.eligible else "blocked"


@dataclass(frozen=True)
class HybridOutcome:
    """What hybrid did with one arriving ticket."""

    ticket_id: str
    version: str = HYBRID_CORRELATION_VERSION
    # The deterministic pass, always run.
    deterministic_candidate_id: str | None = None
    deterministic_attached: bool = False
    deterministic_score: float | None = None
    # The fallback stage. Empty when deterministic already attached.
    fallback_decisions: tuple[FallbackDecision, ...] = ()
    semantic_invoked: bool = False
    semantic_candidate_id: str | None = None
    semantic_score: float | None = None
    semantic_failed: bool = False
    failure_reason: str | None = None
    embedding_model: str | None = None
    # The answer.
    final_candidate_id: str | None = None
    result: CorrelationResult | None = field(default=None, repr=False)

    @property
    def attached(self) -> bool:
        return self.final_candidate_id is not None

    @property
    def path(self) -> str:
        """Which route produced the answer. Reported in metrics and in the UI."""
        if self.deterministic_attached:
            return "deterministic"
        if self.semantic_invoked:
            return "semantic_fallback"
        return "deterministic_reject"


def _identifier_conflict(
    arriving, members: Sequence
) -> str | None:
    """Different error codes named on both sides.

    The deterministic baseline rewards a *shared* identifier and is silent about differing
    ones — its entity signal has no conflicting branch. That silence is a gap here
    specifically: PR04 in the authored set (`ERR_AUTH_STALL` against `ERR_TOKEN_EXPIRED`)
    is the single most semantically similar pair in the whole set, scoring higher than
    either genuine paraphrase. It is exactly where an embedding would do damage.

    Detected in the hybrid gate rather than in the baseline scoring, because changing the
    baseline would change results M5 and M6 already measured.
    """
    incoming = {
        value for value in arriving.identifiers if value.startswith("error_code:")
    }
    if not incoming:
        return None
    for member in members:
        theirs = {
            value for value in member.identifiers if value.startswith("error_code:")
        }
        if theirs and not (theirs & incoming):
            return (
                "identifier conflict: "
                + ", ".join(sorted(v.split(":", 1)[1] for v in incoming))
                + " against "
                + ", ".join(sorted(v.split(":", 1)[1] for v in theirs))
                + " — different failure mechanisms named explicitly"
            )
    return None


def _conflicts(scores: Sequence[PairwiseScore]) -> tuple[str, ...]:
    """Hard conflicts across the candidate's members.

    These are the reasons semantic evidence must never be allowed to argue with. A
    different service, or an issue-type pair the rules already call contradictory, is
    positive evidence *against* grouping — not an absence of evidence that an embedding
    could supply.
    """
    blocking: list[str] = []
    for score in scores:
        for signal in score.signals:
            if signal.direction is not Direction.CONFLICTING:
                continue
            if signal.component is Component.SERVICE:
                blocking.append(f"service conflict: {signal.detail}")
            elif signal.component is Component.ISSUE_TYPE:
                blocking.append(f"issue-type conflict: {signal.detail}")
            elif signal.component is Component.ENTITY:
                blocking.append(f"identifier conflict: {signal.detail}")
    return tuple(dict.fromkeys(blocking))


def _lexical_component(score: PairwiseScore) -> float:
    for signal in score.signals:
        if signal.component is Component.LEXICAL:
            return signal.score
    return 0.0


def evaluate_fallback(
    candidate: CandidateIncident,
    scores: Sequence[PairwiseScore],
    arriving=None,
    members: Sequence = (),
) -> FallbackDecision:
    """Is semantic evidence worth computing against this candidate?

    Answered entirely from the deterministic pass. Four conditions, and the fourth is the
    point: fallback is for tickets whose *wording* let them down, not for tickets that are
    merely near the line.
    """
    blocking = list(_conflicts(scores))
    reasons: list[str] = []

    if arriving is not None:
        conflict = _identifier_conflict(arriving, members)
        if conflict:
            blocking.append(conflict)

    if not scores:
        return FallbackDecision(
            candidate_id=candidate.id,
            eligible=False,
            blocking_reasons=("no comparable members",),
        )

    # 1. The candidate must still be open to new reports. A quiet candidate is closed on
    #    the deterministic baseline's own rule, and embeddings do not reopen it.
    nearest = max(score.time_score for score in scores)
    if nearest < TIME_LINK_MIN:
        oldest = min(score.minutes_apart for score in scores)
        blocking.append(
            f"outside the active window: nearest member is {oldest:.0f} minutes away "
            f"(candidates stop accepting reports after {CANDIDATE_IDLE_MINUTES:.0f})"
        )
    else:
        reasons.append(f"within the active window ({min(s.minutes_apart for s in scores):.0f}m)")

    # 2. No hard conflict. Recorded above.
    if not _conflicts(scores):
        reasons.append("no service, issue-type or identifier conflict")

    # 3. Some positive operational overlap — otherwise there is nothing for semantic
    #    evidence to complete, and a high embedding score alone would be the only thing
    #    holding the group together.
    supporting = {
        signal.component
        for score in scores
        for signal in score.signals
        if signal.direction is Direction.SUPPORTING
        and signal.component in (Component.SERVICE, Component.ISSUE_TYPE, Component.ENTITY)
    }
    if supporting:
        reasons.append(
            "operational agreement on "
            + ", ".join(sorted(component.value for component in supporting))
        )
    else:
        blocking.append(
            "no operational agreement: service, issue type and identifiers all say "
            "nothing, so semantic similarity would be the only evidence"
        )

    # 4. Lexical overlap is the weak link. This is what separates "a paraphrase we should
    #    look at again" from "a ticket that is simply near the threshold".
    weakest_lexical = min(_lexical_component(score) for score in scores)
    if weakest_lexical <= LEXICAL_WEAKNESS_MAX:
        reasons.append(
            f"low lexical overlap ({weakest_lexical:.2f}) is the limiting signal"
        )
    else:
        blocking.append(
            f"lexical overlap is {weakest_lexical:.2f}, not the limiting signal; "
            "semantic similarity would be answering a question that was not asked"
        )

    return FallbackDecision(
        candidate_id=candidate.id,
        eligible=not blocking,
        reasons=tuple(reasons),
        blocking_reasons=tuple(dict.fromkeys(blocking)),
        deterministic_score=min((score.score for score in scores), default=None),
    )


def correlate_pairwise(
    tickets: Sequence[CorrelationTicket],
    arriving_id: str,
    model=None,
) -> HybridOutcome:
    """Deterministic first; the pairwise classifier only where the M16 gate allows.

    The gate is reused **unchanged**. That is what makes the comparison meaningful: the
    classifier runs on exactly the slice where cosine failed, so the two are answering the
    same question about the same tickets.

    The classifier cannot overrule anything. A hard conflict blocks before it is consulted,
    and complete-link cohesion still has to accept the resulting group.
    """
    deterministic = correlate(tickets)
    attached = next(
        (c for c in deterministic.candidates if arriving_id in c.ticket_ids), None
    )
    if attached is not None:
        return HybridOutcome(
            ticket_id=arriving_id,
            version=PAIRWISE_VERSION,
            deterministic_candidate_id=attached.id,
            deterministic_attached=True,
            deterministic_score=attached.score,
            final_candidate_id=attached.id,
            result=deterministic,
        )

    decisions = _fallback_decisions(tickets, arriving_id, deterministic)
    eligible = {d.candidate_id for d in decisions if d.eligible}
    if not eligible or model is None:
        return HybridOutcome(
            ticket_id=arriving_id,
            version=PAIRWISE_VERSION,
            fallback_decisions=decisions,
            result=deterministic,
        )

    from app.pairwise import PairwiseModelError, extract

    by_id = {ticket.id: ticket for ticket in tickets}
    arriving = by_id[arriving_id]

    best: tuple[float, str] | None = None
    try:
        for candidate in deterministic.candidates:
            if candidate.id not in eligible:
                continue
            members = [
                by_id[member_id]
                for member_id in candidate.ticket_ids
                if member_id in by_id and member_id != arriving_id
            ]
            if not members:
                continue
            score = model.score(extract(arriving, members))
            if best is None or score > best[0]:
                best = (score, candidate.id)
    except PairwiseModelError as error:
        return HybridOutcome(
            ticket_id=arriving_id,
            version=PAIRWISE_VERSION,
            fallback_decisions=decisions,
            semantic_failed=True,
            failure_reason=f"pairwise model failed: {error}",
            result=deterministic,
        )

    if best is None or best[0] < model.threshold:
        return HybridOutcome(
            ticket_id=arriving_id,
            version=PAIRWISE_VERSION,
            fallback_decisions=decisions,
            semantic_invoked=True,
            semantic_score=round(best[0], 4) if best else None,
            embedding_model=f"{model.model_class}/{model.version}",
            result=deterministic,
        )

    # Above threshold. Cohesion still has to accept it — the classifier says "plausibly
    # belongs", complete linkage says "the group survives it", and both must agree.
    score, candidate_id = best
    group = next(c for c in deterministic.candidates if c.id == candidate_id)
    return HybridOutcome(
        ticket_id=arriving_id,
        version=PAIRWISE_VERSION,
        fallback_decisions=decisions,
        semantic_invoked=True,
        semantic_candidate_id=candidate_id,
        semantic_score=round(score, 4),
        embedding_model=f"{model.model_class}/{model.version}",
        final_candidate_id=candidate_id,
        result=deterministic.model_copy(
            update={
                "candidates": tuple(
                    c.model_copy(update={"ticket_ids": (*c.ticket_ids, arriving_id)})
                    if c.id == candidate_id
                    else c
                    for c in deterministic.candidates
                )
            }
        ),
    )


def correlate_hybrid(
    tickets: Sequence[CorrelationTicket],
    arriving_id: str,
    similarity: SemanticSimilarity | None = None,
) -> HybridOutcome:
    """Deterministic first; semantic only for candidates that earned it.

    `similarity` is a *factory-provided* provider, not a prepared one — nothing is
    embedded unless a candidate passes eligibility. Passing None disables fallback
    entirely, which is what the deterministic-only comparison runs.
    """
    deterministic = correlate(tickets)
    attached = next(
        (c for c in deterministic.candidates if arriving_id in c.ticket_ids), None
    )

    if attached is not None:
        # The fast path. No embedding is computed, and none is needed: the deterministic
        # baseline already found enough evidence.
        return HybridOutcome(
            ticket_id=arriving_id,
            deterministic_candidate_id=attached.id,
            deterministic_attached=True,
            deterministic_score=attached.score,
            final_candidate_id=attached.id,
            result=deterministic,
        )

    decisions = _fallback_decisions(tickets, arriving_id, deterministic)
    eligible = {decision.candidate_id for decision in decisions if decision.eligible}

    if not eligible or similarity is None:
        return HybridOutcome(
            ticket_id=arriving_id,
            fallback_decisions=decisions,
            result=deterministic,
        )

    # Only now is anything embedded, and only for the arriving ticket plus the members of
    # candidates that passed. Cached vectors mean an existing member usually costs nothing.
    members = {
        ticket_id
        for candidate in deterministic.candidates
        if candidate.id in eligible
        for ticket_id in candidate.ticket_ids
    } | {arriving_id}
    subject = [ticket for ticket in tickets if ticket.id in members]

    try:
        similarity.prepare(subject)
    except Exception as error:  # noqa: BLE001 - any provider failure, reported as itself
        return HybridOutcome(
            ticket_id=arriving_id,
            fallback_decisions=decisions,
            semantic_failed=True,
            failure_reason=f"embedding provider unavailable: {error}",
            result=deterministic,
        )

    # From here the scoring is exactly `semantic-correlation-v1` — same weights, same
    # complete linkage, same cohesion check. Hybrid chooses *when* to run it, never how.
    try:
        semantic = correlate(subject, similarity)
    except Exception as error:  # noqa: BLE001
        return HybridOutcome(
            ticket_id=arriving_id,
            fallback_decisions=decisions,
            semantic_invoked=True,
            semantic_failed=True,
            failure_reason=f"semantic correlation failed: {error}",
            embedding_model=similarity.identity,
            result=deterministic,
        )

    group = next((c for c in semantic.candidates if arriving_id in c.ticket_ids), None)

    # An attachment only counts if it is to a candidate that passed eligibility. Semantic
    # evidence supplies a missing signal; it does not get to propose a grouping the
    # deterministic stage refused on a hard conflict.
    if group is not None and not _matches_eligible(group, deterministic, eligible):
        return HybridOutcome(
            ticket_id=arriving_id,
            fallback_decisions=decisions,
            semantic_invoked=True,
            semantic_score=group.score,
            embedding_model=similarity.identity,
            failure_reason=(
                "semantic grouping did not correspond to a candidate that passed "
                "fallback eligibility"
            ),
            result=deterministic,
        )

    return HybridOutcome(
        ticket_id=arriving_id,
        fallback_decisions=decisions,
        semantic_invoked=True,
        semantic_candidate_id=group.id if group else None,
        semantic_score=group.score if group else None,
        embedding_model=similarity.identity,
        final_candidate_id=group.id if group else None,
        result=semantic if group else deterministic,
    )


def _fallback_decisions(
    tickets: Sequence[CorrelationTicket],
    arriving_id: str,
    deterministic: CorrelationResult,
) -> tuple[FallbackDecision, ...]:
    """Eligibility per candidate, from the deterministic signals already computed."""
    ordered = sorted(tickets, key=lambda ticket: (ticket.created_at, ticket.id))
    corpus = Corpus()
    features = {}
    for ticket in ordered:
        prepared = prepare(ticket)
        corpus.observe(prepared.tokens)
        features[ticket.id] = prepared

    arriving = features.get(arriving_id)
    if arriving is None:
        return ()

    decisions = []
    for candidate in deterministic.candidates:
        scores = [
            score_pair(arriving, features[member_id], corpus, None)
            for member_id in candidate.ticket_ids
            if member_id in features and member_id != arriving_id
        ]
        if _attaches(scores):
            # Already qualified deterministically; nothing for fallback to add.
            continue
        members = [
            features[member_id]
            for member_id in candidate.ticket_ids
            if member_id in features and member_id != arriving_id
        ]
        decisions.append(evaluate_fallback(candidate, scores, arriving, members))
    return tuple(decisions)


def _matches_eligible(
    group: CandidateIncident, deterministic: CorrelationResult, eligible: set[str]
) -> bool:
    """Does this semantic grouping continue a candidate that passed eligibility?

    Matched by membership overlap: the semantic run may name the group differently, but
    it is the same incident if it shares members with one that qualified.
    """
    for candidate in deterministic.candidates:
        if candidate.id not in eligible:
            continue
        if set(candidate.ticket_ids) & set(group.ticket_ids):
            return True
    return False
