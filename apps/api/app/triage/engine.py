"""Deterministic triage.

    ticket text -> normalize -> match phrases -> score -> predictions + signals

No model, no similarity, no learned weights. Given the same text and the same rule
tables, the output is identical every time, and every number in it traces back to a
phrase an engineer put in `rules.py`.
"""

from collections import defaultdict
from collections.abc import Iterable

from app.domain.models import Ticket, TicketPriority
from app.triage.models import (
    IssueType,
    PredictionStatus,
    ScoredCandidate,
    SignalType,
    SourceField,
    TriageInput,
    TriagePrediction,
    TriageResult,
    TriageSignal,
)
from app.triage.normalize import contains_phrase, normalize
from app.triage.rules import (
    AMBIGUITY_MARGIN,
    ISSUE_RULES,
    LOWEST_BAND,
    NO_EVIDENCE_PRIORITY,
    PRIORITY_BANDS,
    PRIORITY_RULES,
    SERVICE_RULES,
    TITLE_WEIGHT_MULTIPLIER,
    TRIAGE_VERSION,
    Phrase,
)

_SERVICE_NAMES = {rule.service_id: rule.display_name for rule in SERVICE_RULES}


def triage(request: TriageInput) -> TriageResult:
    """Classifies one ticket's text."""
    fields: dict[SourceField, str] = {
        "title": normalize(request.title),
        "description": normalize(request.description),
    }

    signals: list[TriageSignal] = []

    service_scores: dict[str, float] = {}
    for rule in SERVICE_RULES:
        matches = _match(rule.phrases, fields)
        target = f"service:{rule.service_id}"
        signals.extend(
            _to_signal(match, SignalType.SERVICE_TERM, target) for match in matches
        )
        if matches:
            service_scores[rule.service_id] = _total(matches)

    issue_scores: dict[str, float] = {}
    for issue_rule in ISSUE_RULES:
        matches = _match(issue_rule.phrases, fields)
        target = f"issue_type:{issue_rule.issue_type.value}"
        signals.extend(
            _to_signal(match, SignalType.ISSUE_TERM, target) for match in matches
        )
        if matches:
            issue_scores[issue_rule.issue_type.value] = _total(matches)

    priority_matches: list[tuple[Phrase, SourceField, float, SignalType]] = []
    for priority_rule in PRIORITY_RULES:
        for match in _match(priority_rule.phrases, fields):
            signals.append(_to_signal(match, priority_rule.signal_type, "priority"))
            priority_matches.append((*match, priority_rule.signal_type))

    return TriageResult(
        ticket_id=request.ticket_id,
        version=TRIAGE_VERSION,
        service=_classify(service_scores, _SERVICE_NAMES, "service vocabulary"),
        issue_type=_classify(
            issue_scores,
            {},
            "issue vocabulary",
            unknown_value=IssueType.UNKNOWN.value,
        ),
        priority=_score_priority(priority_matches),
        signals=tuple(signals),
    )


def triage_ticket(ticket: Ticket) -> TriageResult:
    """Triages a stored ticket from its text only.

    The ticket's own `priority` and `service_id` are deliberately not read: triage
    exists to produce them, and feeding them back in would make every evaluation on
    already-triaged tickets meaningless.
    """
    return triage(
        TriageInput(
            ticket_id=ticket.id, title=ticket.title, description=ticket.description
        )
    )


Match = tuple[Phrase, SourceField, float]


def _match(phrases: Iterable[Phrase], fields: dict[SourceField, str]) -> list[Match]:
    """Finds each phrase at most once, at its strongest position.

    A phrase in both title and body is one piece of evidence, not two, and a shorter
    phrase contained in a longer match ("log in" inside "cannot log in") is dropped so
    overlapping vocabulary cannot inflate a score.
    """
    found: list[Match] = []
    for phrase in phrases:
        for field, multiplier in (
            ("title", TITLE_WEIGHT_MULTIPLIER),
            ("description", 1.0),
        ):
            if contains_phrase(fields[field], phrase.text):
                found.append((phrase, field, phrase.weight * multiplier))
                break

    found.sort(key=lambda match: len(match[0].text), reverse=True)
    accepted: list[Match] = []
    for match in found:
        if any(match[0].text in other[0].text for other in accepted):
            continue
        accepted.append(match)
    return accepted


def _total(matches: list[Match]) -> float:
    return round(sum(weight for _, _, weight in matches), 2)


def _to_signal(match: Match, signal_type: SignalType, target: str) -> TriageSignal:
    phrase, field, weight = match
    return TriageSignal(
        signal_type=signal_type,
        matched_text=phrase.text,
        normalized_value=phrase.normalized_value,
        weight=round(weight, 2),
        source_field=field,
        target=target,
    )


def _classify(
    scores: dict[str, float],
    display: dict[str, str],
    vocabulary: str,
    *,
    unknown_value: str | None = None,
) -> TriagePrediction:
    """Picks a winner, or declines to.

    `unknown_value` is the taxonomy's own name for "none of these" where it has one.
    Issue types do (`unknown`); a service id does not, so an unrecognised service stays
    null rather than being given a fake id.
    """
    if not scores:
        return TriagePrediction(
            value=unknown_value,
            status=PredictionStatus.UNKNOWN,
            score=0.0,
            margin=0.0,
            candidates=(),
            explanation=f"No {vocabulary} matched.",
        )

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    candidates = tuple(ScoredCandidate(value=key, score=score) for key, score in ranked)
    top_value, top_score = ranked[0]
    runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = round(top_score - runner_up_score, 2)

    def label(key: str) -> str:
        return display.get(key, key)

    if len(ranked) > 1 and margin < AMBIGUITY_MARGIN:
        return TriagePrediction(
            value=None,
            status=PredictionStatus.AMBIGUOUS,
            score=top_score,
            margin=margin,
            candidates=candidates,
            explanation=(
                f"{label(top_value)} ({top_score}) and {label(ranked[1][0])} "
                f"({runner_up_score}) are within {margin} — too close to separate."
            ),
        )

    runner_up = (
        f"; next closest {label(ranked[1][0])} ({runner_up_score})"
        if len(ranked) > 1
        else ""
    )
    return TriagePrediction(
        value=top_value,
        status=PredictionStatus.CLASSIFIED,
        score=top_score,
        margin=margin,
        candidates=candidates,
        explanation=f"{label(top_value)} scored {top_score}{runner_up}.",
    )


def _score_priority(
    matches: list[tuple[Phrase, SourceField, float, SignalType]],
) -> TriagePrediction:
    if not matches:
        return TriagePrediction(
            value=NO_EVIDENCE_PRIORITY.value,
            status=PredictionStatus.DEFAULT,
            score=0.0,
            margin=0.0,
            candidates=(),
            explanation=(
                f"No urgency, scope, or impact phrases matched; defaulted to "
                f"{NO_EVIDENCE_PRIORITY.value}."
            ),
        )

    # One contribution per dimension: its strongest match. See rules.PRIORITY_BANDS.
    strongest: dict[SignalType, float] = {}
    by_type: dict[SignalType, list[str]] = defaultdict(list)
    for phrase, field, weight, signal_type in matches:
        current = strongest.get(signal_type)
        if current is None or abs(weight) > abs(current):
            strongest[signal_type] = weight
        by_type[signal_type].append(f"{weight:+g} {phrase.text!r} ({field})")

    total = round(sum(strongest.values()), 2)
    priority = _band(total)

    parts = "; ".join(
        f"{signal_type.value} {strongest[signal_type]:+g} (from {', '.join(entries)})"
        for signal_type, entries in sorted(by_type.items(), key=lambda kv: kv[0].value)
    )
    return TriagePrediction(
        value=priority.value,
        status=PredictionStatus.CLASSIFIED,
        score=total,
        margin=round(total - _band_floor(priority), 2),
        candidates=(ScoredCandidate(value=priority.value, score=total),),
        explanation=f"Score {total} [{parts}] falls in the {priority.value} band.",
    )


def _band(score: float) -> TicketPriority:
    for threshold, priority in PRIORITY_BANDS:
        if score >= threshold:
            return priority
    return LOWEST_BAND


def _band_floor(priority: TicketPriority) -> float:
    for threshold, banded in PRIORITY_BANDS:
        if banded is priority:
            return threshold
    return 0.0


ISSUE_TYPE_VALUES = tuple(issue.value for issue in IssueType)
