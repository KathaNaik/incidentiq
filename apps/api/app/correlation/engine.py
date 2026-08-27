"""Incremental correlation.

Tickets are processed in chronological order and each one is compared only against
candidates that are still active. That is deliberate: the product needs to notice an
incident forming *while it forms*, and an evaluation that lets a ticket from Thursday
influence a grouping made on Monday would measure something the running system cannot do.

Attachment rule (see `rules.py` for the numbers):

1. content similarity against **every** member clears `CONTENT_LINK_MIN` — complete
   linkage, so a chain of pairwise-similar-but-collectively-unrelated tickets cannot
   accumulate into one group;
2. time proximity to the **nearest** member clears `TIME_LINK_MIN` — a long-running
   incident keeps absorbing reports, but a quiet gap ends it;
3. the blended score clears `LINK_THRESHOLD`.

A ticket that matches nothing stays on its own. Standalone is a real answer, not a
failure to decide.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.correlation.models import (
    CandidateIncident,
    Confidence,
    CorrelationResult,
    CorrelationSignal,
    CorrelationTicket,
    Direction,
    PairwiseScore,
)
from app.correlation.pairwise import Corpus, TicketFeatures, prepare, score_pair
from app.correlation.rules import (
    CANDIDATE_IDLE_MINUTES,
    COHESION_MIN,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONTENT_LINK_MIN,
    CORRELATION_VERSION,
    LINK_THRESHOLD,
    SEMANTIC_CORRELATION_VERSION,
    TIME_LINK_MIN,
)
from app.correlation.semantic import SemanticSimilarity


@dataclass
class _OpenCandidate:
    members: list[TicketFeatures] = field(default_factory=list)
    pairs: list[PairwiseScore] = field(default_factory=list)

    @property
    def last_seen(self) -> datetime:
        return max(member.ticket.created_at for member in self.members)

    @property
    def first_seen(self) -> datetime:
        return min(member.ticket.created_at for member in self.members)


def correlate(
    tickets: Sequence[CorrelationTicket],
    similarity: SemanticSimilarity | None = None,
) -> CorrelationResult:
    """Groups tickets into candidate incidents.

    Called without `similarity` this is the deterministic baseline, unchanged. Passing a
    `SemanticSimilarity` adds embedding similarity as one more signal and stamps the
    result with the semantic version — the candidate generation, the linkage rule and
    every guardrail are identical, so a difference in the metrics is attributable to the
    signal rather than to a different algorithm.
    """
    ordered = sorted(tickets, key=lambda ticket: (ticket.created_at, ticket.id))
    corpus = Corpus()
    candidates: list[_OpenCandidate] = []

    if similarity is not None:
        # Embedded once, up front. Vectors depend only on a ticket's own text, so this
        # gives no ticket knowledge of any other — the incremental discipline is about
        # what influences a *grouping decision*, and that still only sees the past.
        similarity.prepare(ordered)

    for ticket in ordered:
        features = prepare(ticket)
        # The corpus grows with each arrival, so token weights only ever reflect what
        # has already been seen.
        corpus.observe(features.tokens)

        best: tuple[float, _OpenCandidate, list[PairwiseScore]] | None = None
        for candidate in candidates:
            if _idle_minutes(candidate, ticket.created_at) > CANDIDATE_IDLE_MINUTES:
                continue
            scores = [
                score_pair(features, member, corpus, similarity)
                for member in candidate.members
            ]
            if not _attaches(scores):
                continue
            blended = min(score.score for score in scores)
            if best is None or blended > best[0]:
                best = (blended, candidate, scores)

        if best is None:
            candidates.append(_OpenCandidate(members=[features]))
        else:
            _, candidate, scores = best
            candidate.members.append(features)
            candidate.pairs.extend(scores)

    return _build_result(candidates, similarity is not None)


def _idle_minutes(candidate: _OpenCandidate, now: datetime) -> float:
    return (now - candidate.last_seen).total_seconds() / 60.0


def _attaches(scores: list[PairwiseScore]) -> bool:
    """The three conditions, in the order they are cheapest to reason about."""
    if min(score.content_score for score in scores) < CONTENT_LINK_MIN:
        return False
    if max(score.time_score for score in scores) < TIME_LINK_MIN:
        return False
    return min(score.score for score in scores) >= LINK_THRESHOLD


def _build_result(
    candidates: list[_OpenCandidate], semantic: bool
) -> CorrelationResult:
    grouped: list[CandidateIncident] = []
    standalone: list[str] = []

    for candidate in sorted(candidates, key=lambda c: (c.first_seen, c.members[0].ticket.id)):
        if len(candidate.members) < 2:
            standalone.append(candidate.members[0].ticket.id)
            continue

        cohesion = round(
            sum(pair.score for pair in candidate.pairs) / len(candidate.pairs), 4
        )
        if cohesion < COHESION_MIN:
            # Belt and braces: complete linkage should already prevent this, but a
            # group nobody can justify is dissolved rather than shipped.
            standalone.extend(member.ticket.id for member in candidate.members)
            continue

        grouped.append(_to_candidate(candidate, cohesion))

    return CorrelationResult(
        version=SEMANTIC_CORRELATION_VERSION if semantic else CORRELATION_VERSION,
        ticket_count=sum(len(c.members) for c in candidates),
        candidates=tuple(grouped),
        standalone_ticket_ids=tuple(sorted(standalone)),
    )


def _to_candidate(candidate: _OpenCandidate, cohesion: float) -> CandidateIncident:
    members = sorted(candidate.members, key=lambda m: (m.ticket.created_at, m.ticket.id))
    services = {member.service_id for member in members}
    issues = {member.issue_type for member in members}

    supporting, conflicting = _summarize(candidate.pairs)

    # Counted from the tickets themselves. If nobody is named, the answer is "unknown"
    # rather than a fabricated blast radius.
    reporters = {
        member.ticket.reported_by
        for member in members
        if member.ticket.reported_by is not None
    }

    return CandidateIncident(
        # Derived from the first ticket, so the same input always yields the same id.
        id=f"cand-{members[0].ticket.id}",
        ticket_ids=tuple(member.ticket.id for member in members),
        score=cohesion,
        confidence=_confidence(cohesion),
        first_seen=members[0].ticket.created_at,
        last_seen=members[-1].ticket.created_at,
        service_id=next(iter(services)) if len(services) == 1 else None,
        issue_type=next(iter(issues)) if len(issues) == 1 else None,
        ticket_count=len(members),
        distinct_reporters=len(reporters) if reporters else None,
        supporting_signals=supporting,
        conflicting_signals=conflicting,
        member_pairs=tuple(
            sorted(candidate.pairs, key=lambda pair: (pair.ticket_a, pair.ticket_b))
        ),
    )


def _summarize(
    pairs: list[PairwiseScore],
) -> tuple[tuple[CorrelationSignal, ...], tuple[CorrelationSignal, ...]]:
    """One representative signal per component per direction.

    The strongest example of each kind of evidence, rather than every pairwise signal —
    a five-ticket group produces ten pairs and fifty signals, which explains nothing.
    """
    strongest: dict[tuple[str, str], CorrelationSignal] = {}
    for pair in pairs:
        for signal in pair.signals:
            if signal.direction is Direction.NEUTRAL:
                continue
            key = (signal.component.value, signal.direction.value)
            current = strongest.get(key)
            if current is None or abs(signal.score) > abs(current.score):
                strongest[key] = signal

    supporting = tuple(
        signal
        for (_, direction), signal in sorted(strongest.items())
        if direction == Direction.SUPPORTING.value
    )
    conflicting = tuple(
        signal
        for (_, direction), signal in sorted(strongest.items())
        if direction == Direction.CONFLICTING.value
    )
    return supporting, conflicting


def _confidence(score: float) -> Confidence:
    if score >= CONFIDENCE_HIGH:
        return Confidence.HIGH
    if score >= CONFIDENCE_MEDIUM:
        return Confidence.MEDIUM
    return Confidence.LOW
