"""Safe reconciliation of a recomputed cluster onto a durable candidate.

`correlate()` is stateless: every intake re-derives clusters from the window, knowing
nothing about what is already persisted. Intake then has to decide which durable
candidate a fresh cluster *is*. That question is answered by membership overlap, and
answering it is fine — a candidate an operator is already looking at should keep its
identity when it grows.

The defect v2 closes is that overlap was answering a second question it has no business
answering: **whether the arriving ticket belongs there at all.**

Concretely, from the M19 acceptance run:

    durable candidate  = {A, B, C}   (C attached by an operator through review)
    recomputed cluster = {C, D}      (legitimate on its own terms, 0.6369)

The cluster overlaps the candidate at C, so intake mapped it onto that candidate and
assigned every cluster member to it. D thereby joined A and B having been scored only
against C — 0.4054 and 0.4577 against the members it actually joined, both far below the
0.60 attachment threshold. A performance complaint silently became part of a sign-in
incident.

Nothing about the operator's decision was wrong, and nothing about the cluster was wrong.
The bug is that *identity* reconciliation was allowed to imply *membership*.

## The rule

An arriving ticket may join a durable candidate only if it clears the engine's own
attachment rule against that candidate's **automatically-established members**.

Operator-confirmed members are deliberately not part of that comparison, and this is the
subtle part, so it is worth being exact about why it is not "human decisions are
second-class data":

- A confirmed ticket stays a full member of the incident. It shows up in evidence, in
  the timeline, in candidate metadata, in investigations. Nothing is removed.
- What it does not do is *vouch for a stranger*. The operator answered one question about
  one ticket. That answer is not evidence about some future ticket, in either direction.

That last clause matters in both directions, and measurement is what forced the design.
Requiring complete linkage against the full durable membership fixes the false merge but
breaks the honest case: a genuine follow-up scored 0.5366 against the widened membership
and would have been refused, purely because the confirmed paraphrase is worded unlike
everything else. Admission against the automatic core gets both right:

    unrelated D        vs {A, B} -> min 0.4054  refused
    genuine follow-up  vs {A, B} -> min 0.6256  attached

So a confirmation neither smuggles a stranger in nor locks the incident down. Membership
provenance comes from `correlation_reviews`; no schema change was needed to know which
members an operator placed.

No weight, threshold, or time-decay parameter differs between v1 and v2.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.correlation.engine import attaches
from app.correlation.models import CorrelationTicket, PairwiseScore
from app.correlation.pairwise import Corpus, prepare, score_pair


@dataclass(frozen=True)
class Admission:
    """Whether an arriving ticket earned membership, and the numbers behind it."""

    admitted: bool
    scores: tuple[PairwiseScore, ...]
    reason: str

    @property
    def weakest(self) -> float | None:
        return min((s.score for s in self.scores), default=None)


def admits(
    arriving: CorrelationTicket,
    members: Sequence[CorrelationTicket],
    window: Sequence[CorrelationTicket],
) -> Admission:
    """Applies the engine's attachment rule to a durable candidate's membership.

    `window` is the same set of tickets the clustering pass saw. Token weights are
    corpus-relative, so scoring against a corpus built from anything else would answer a
    slightly different question than the one clustering just answered.
    """
    if not members:
        # A candidate with no automatically-established members cannot vouch for anyone.
        # Refusing sends the ticket to review, which is the conservative direction.
        return Admission(False, (), "candidate has no automatically correlated members")

    corpus = Corpus()
    features = {}
    for ticket in sorted(window, key=lambda t: (t.created_at, t.id)):
        prepared = prepare(ticket)
        features[ticket.id] = prepared
        corpus.observe(prepared.tokens)

    arriving_features = features.get(arriving.id) or prepare(arriving)
    scores = tuple(
        score_pair(arriving_features, features.get(m.id) or prepare(m), corpus)
        for m in members
    )

    if attaches(scores):
        return Admission(
            True,
            scores,
            f"cleared the attachment rule against all {len(scores)} "
            f"automatically correlated member(s)",
        )

    weakest = min(scores, key=lambda s: s.score)
    return Admission(
        False,
        scores,
        (
            f"scored {weakest.score} against {weakest.ticket_b}, below the linkage "
            f"threshold; the grouping that suggested this candidate did not include "
            f"every member the ticket would be joining"
        ),
    )


__all__ = ["Admission", "admits"]
