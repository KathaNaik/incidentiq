"""Pairwise scoring: how much evidence is there that two tickets are one incident?

Each component answers a separate question and reports its own signal, so a score can
always be read back as a list of reasons rather than a number.
"""

import math
from collections import Counter
from dataclasses import dataclass, field

from app.correlation.entities import extract_entities
from app.correlation.models import (
    Component,
    CorrelationSignal,
    CorrelationTicket,
    Direction,
    PairwiseScore,
)
from app.correlation.rules import (
    COMPATIBLE_ISSUE_SCORE,
    COMPATIBLE_ISSUE_TYPES,
    CONTRADICTORY_ISSUE_SCORE,
    CONTRADICTORY_ISSUE_TYPES,
    DIFFERENT_SERVICE_SCORE,
    MIN_TOKEN_LENGTH,
    SAME_ISSUE_SCORE,
    SAME_SERVICE_SCORE,
    SHARED_IDENTIFIER_SCORE,
    SHARED_SYMPTOM_SCORE,
    STOP_WORDS,
    TIME_HALF_LIFE_MINUTES,
    UNKNOWN_SERVICE_SCORE,
    W_ENTITY,
    W_ISSUE,
    W_LEXICAL,
    W_SERVICE,
    W_TIME,
)
from app.triage import TriageInput, triage
from app.triage.models import IssueType, SignalType
from app.triage.normalize import normalize


@dataclass(frozen=True)
class TicketFeatures:
    """Everything correlation knows about one ticket, computed once."""

    ticket: CorrelationTicket
    service_id: str | None
    issue_type: str | None
    tokens: frozenset[str]
    identifiers: frozenset[str]
    symptoms: frozenset[str]


def prepare(ticket: CorrelationTicket) -> TicketFeatures:
    """Derives correlation features from a ticket's own text.

    Triage is reused rather than reimplemented: it already turns text into a service, an
    issue type, and normalized symptom values. A service the ticket states outright wins
    over the predicted one — a reporter naming their service is better evidence than our
    keyword guess.
    """
    text = f"{ticket.title} {ticket.description}"
    result = triage(
        TriageInput(
            ticket_id=ticket.id, title=ticket.title, description=ticket.description
        )
    )

    issue_type = result.issue_type.value
    return TicketFeatures(
        ticket=ticket,
        service_id=ticket.service_id or result.service.value,
        issue_type=None if issue_type == IssueType.UNKNOWN.value else issue_type,
        tokens=frozenset(_content_tokens(text)),
        identifiers=frozenset(
            f"{entity.kind}:{entity.value}" for entity in extract_entities(text)
        ),
        # Triage's canonical values, so "everything is down" and "service unavailable"
        # count as the same symptom instead of two unrelated strings.
        #
        # Service vocabulary is excluded: the service component already scores that
        # agreement, and counting "dashboard" again here is what makes two unrelated
        # dashboard tickets look like one incident.
        symptoms=frozenset(
            signal.normalized_value
            for signal in result.signals
            if signal.signal_type is not SignalType.SERVICE_TERM
        ),
    )


def _content_tokens(text: str) -> set[str]:
    """Content words, singularized the same crude way the phrase matcher works.

    Without this, "dashboards" and "dashboard" are two unrelated tokens and two reports
    of the same failure share nothing.
    """
    return {
        _singular(token)
        for token in normalize(text).split()
        if len(token) >= MIN_TOKEN_LENGTH and token not in STOP_WORDS
    }


def _singular(token: str) -> str:
    if len(token) > MIN_TOKEN_LENGTH and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


@dataclass
class Corpus:
    """Document frequencies for inverse-document-frequency weighting.

    Updated as tickets arrive, so a score never depends on a ticket that had not been
    seen yet. This is what stops shared product vocabulary from dominating: in a corpus
    full of dashboard tickets, "dashboard" carries almost no weight, while "ga4" still
    does.
    """

    documents: int = 0
    frequencies: Counter[str] = field(default_factory=Counter)

    def observe(self, tokens: frozenset[str]) -> None:
        self.documents += 1
        self.frequencies.update(tokens)

    def idf(self, token: str) -> float:
        # Smoothed so an unseen token is informative rather than infinite.
        return math.log((self.documents + 1) / (self.frequencies.get(token, 0) + 1)) + 1.0


def time_score(minutes_apart: float) -> float:
    """Exponential decay on the gap between two tickets."""
    return 0.5 ** (abs(minutes_apart) / TIME_HALF_LIFE_MINUTES)


def score_pair(a: TicketFeatures, b: TicketFeatures, corpus: Corpus) -> PairwiseScore:
    minutes = abs((a.ticket.created_at - b.ticket.created_at).total_seconds()) / 60.0

    time_component = _time_signal(minutes)
    content_signals = (
        _service_signal(a, b),
        _issue_signal(a, b),
        _lexical_signal(a, b, corpus),
        _entity_signal(a, b),
    )

    content = round(
        sum(signal.score * signal.weight for signal in content_signals), 4
    )
    blended = round(W_TIME * time_component.score + (1.0 - W_TIME) * content, 4)

    return PairwiseScore(
        ticket_a=a.ticket.id,
        ticket_b=b.ticket.id,
        score=blended,
        content_score=content,
        time_score=time_component.score,
        minutes_apart=round(minutes, 2),
        signals=(time_component, *content_signals),
    )


def _signal(
    component: Component, score: float, weight: float, detail: str, values: tuple = ()
) -> CorrelationSignal:
    if score > 0:
        direction = Direction.SUPPORTING
    elif score < 0:
        direction = Direction.CONFLICTING
    else:
        direction = Direction.NEUTRAL
    return CorrelationSignal(
        component=component,
        direction=direction,
        score=round(score, 4),
        weight=weight,
        detail=detail,
        values=values,
    )


def _time_signal(minutes: float) -> CorrelationSignal:
    score = time_score(minutes)
    if minutes < 1:
        detail = "reported within a minute of each other"
    elif minutes < 60:
        detail = f"reported {minutes:.0f} minutes apart"
    else:
        detail = f"reported {minutes / 60:.1f} hours apart"
    return _signal(Component.TIME, score, W_TIME, detail)


def _service_signal(a: TicketFeatures, b: TicketFeatures) -> CorrelationSignal:
    if a.service_id is None or b.service_id is None:
        return _signal(
            Component.SERVICE,
            UNKNOWN_SERVICE_SCORE,
            W_SERVICE,
            "service unknown for at least one ticket",
        )
    if a.service_id == b.service_id:
        return _signal(
            Component.SERVICE,
            SAME_SERVICE_SCORE,
            W_SERVICE,
            f"same service: {a.service_id}",
            (a.service_id,),
        )
    return _signal(
        Component.SERVICE,
        DIFFERENT_SERVICE_SCORE,
        W_SERVICE,
        f"different services: {a.service_id} vs {b.service_id}",
        (a.service_id, b.service_id),
    )


def _issue_signal(a: TicketFeatures, b: TicketFeatures) -> CorrelationSignal:
    if a.issue_type is None or b.issue_type is None:
        return _signal(
            Component.ISSUE_TYPE, 0.0, W_ISSUE, "issue type unknown for at least one ticket"
        )
    if a.issue_type == b.issue_type:
        return _signal(
            Component.ISSUE_TYPE,
            SAME_ISSUE_SCORE,
            W_ISSUE,
            f"same issue type: {a.issue_type}",
            (a.issue_type,),
        )

    pair = frozenset({a.issue_type, b.issue_type})
    if pair in CONTRADICTORY_ISSUE_TYPES:
        return _signal(
            Component.ISSUE_TYPE,
            CONTRADICTORY_ISSUE_SCORE,
            W_ISSUE,
            f"{a.issue_type} and {b.issue_type} are usually different problems",
            (a.issue_type, b.issue_type),
        )
    if pair in COMPATIBLE_ISSUE_TYPES:
        return _signal(
            Component.ISSUE_TYPE,
            COMPATIBLE_ISSUE_SCORE,
            W_ISSUE,
            f"{a.issue_type} and {b.issue_type} can share a cause",
            (a.issue_type, b.issue_type),
        )
    return _signal(
        Component.ISSUE_TYPE,
        0.0,
        W_ISSUE,
        f"unrelated issue types: {a.issue_type}, {b.issue_type}",
        (a.issue_type, b.issue_type),
    )


def _lexical_signal(
    a: TicketFeatures, b: TicketFeatures, corpus: Corpus
) -> CorrelationSignal:
    """Cosine similarity over IDF-weighted token sets.

    Cosine rather than Jaccard because ticket lengths vary wildly — a one-line report
    and a five-line one describing the same failure share every important word, and
    Jaccard would punish them for the extra prose. Weights come from the running corpus,
    so shared product vocabulary contributes almost nothing while a rare term counts.
    """
    shared = a.tokens & b.tokens
    if not a.tokens or not b.tokens:
        return _signal(Component.LEXICAL, 0.0, W_LEXICAL, "no comparable text")

    def norm(tokens: frozenset[str]) -> float:
        return math.sqrt(sum(corpus.idf(token) ** 2 for token in tokens))

    numerator = sum(corpus.idf(token) ** 2 for token in shared)
    denominator = norm(a.tokens) * norm(b.tokens)
    score = numerator / denominator if denominator else 0.0

    top = tuple(sorted(shared, key=lambda token: (-corpus.idf(token), token))[:5])
    detail = (
        f"{len(shared)} shared terms, weighted overlap {score:.2f}"
        if shared
        else "no shared terms"
    )
    return _signal(Component.LEXICAL, score, W_LEXICAL, detail, top)


def _entity_signal(a: TicketFeatures, b: TicketFeatures) -> CorrelationSignal:
    shared_identifiers = a.identifiers & b.identifiers
    if shared_identifiers:
        return _signal(
            Component.ENTITY,
            SHARED_IDENTIFIER_SCORE,
            W_ENTITY,
            f"shared identifier: {', '.join(sorted(shared_identifiers))}",
            tuple(sorted(shared_identifiers)),
        )

    shared_symptoms = a.symptoms & b.symptoms
    if shared_symptoms:
        return _signal(
            Component.ENTITY,
            SHARED_SYMPTOM_SCORE,
            W_ENTITY,
            f"shared symptoms: {', '.join(sorted(shared_symptoms))}",
            tuple(sorted(shared_symptoms)),
        )

    return _signal(Component.ENTITY, 0.0, W_ENTITY, "no shared identifiers or symptoms")
