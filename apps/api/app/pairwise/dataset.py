"""Building training examples for the pairwise decision.

**Why Polaris, and what it is not.** The authored corpus yields roughly ten positive
examples — not enough to fit a model, let alone evaluate one. Polaris is the only labelled
source available, and its `event_id` lives in a separate file from its features, which is
the isolation M3 built precisely so a label can never become an input.

But Polaris events are **not incidents at IncidentIQ's granularity**. There are fourteen of
them: six `launch_*` campaigns spanning 163–175 days, and seven `outage_*` events spanning
3–4 days at 200–500 tickets each. The product decides whether a ticket joins a candidate
inside a ninety-minute window with a handful of members. "Shares an event_id across four
days" is a different question.

So this module does two things about it, and neither is hidden:

1. **Launches are excluded.** A six-month product rollout is not an incident, and training
   on it would teach the model to group by topic — the exact failure M17 diagnosed.
2. **Outages are windowed.** Positives are drawn from tickets minutes apart inside one
   outage, so the pair resembles the decision the runtime makes. A pair four days apart
   inside the same event is not used as a positive.

That still leaves **seven groups**. Grouped splitting is mandatory and correct, but it
means the effective sample size for generalisation is seven regardless of how many pairs
are generated. Every metric derived from this is reported with that caveat attached.

No raw or processed Polaris content is committed. This reads the gitignored local copy the
M3 download script produces.
"""

import json
import random
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.correlation.models import CorrelationTicket
from app.correlation.rules import CANDIDATE_IDLE_MINUTES
from app.pairwise.features import PairwiseExample, extract

# Positives are drawn inside this window so a training pair resembles a runtime decision.
# Matches the correlation baseline's own idle window rather than inventing a second number.
POSITIVE_WINDOW = timedelta(minutes=CANDIDATE_IDLE_MINUTES)

# Candidates are built from at most this many prior members, matching the size of a live
# candidate. A 500-ticket "candidate" is not a decision the runtime ever makes.
MAX_CANDIDATE_MEMBERS = 4

DATASET_VERSION = "pairwise-polaris-outages-v2"

# Negatives are time-aligned to the arriving ticket. Without this the task is trivially
# solvable by recency, because Polaris outages sit years apart — see `build_examples`.
NEGATIVES_TIME_ALIGNED = True


@dataclass(frozen=True)
class DatasetSummary:
    version: str
    events_used: tuple[str, ...]
    events_excluded: dict[str, str]
    positives: int
    negatives: int
    hard_negatives: int

    @property
    def total(self) -> int:
        return self.positives + self.negatives

    @property
    def positive_rate(self) -> float:
        return round(self.positives / self.total, 4) if self.total else 0.0


def _load(directory: Path) -> tuple[list[dict], dict[str, str]]:
    """Features and the event label, kept in separate structures on purpose."""
    features_path = directory / "features.jsonl"
    labels_path = directory / "labels.jsonl"
    if not features_path.is_file() or not labels_path.is_file():
        raise FileNotFoundError(
            f"Polaris data not found in {directory}. Run "
            "`scripts/download_polaris.py` and `scripts/preprocess_polaris.py`. "
            "The dataset is CC BY-SA and is never committed."
        )
    features = [json.loads(line) for line in features_path.read_text().splitlines()]
    # event_id is read here and used only as label and grouping key. It is never passed
    # into feature extraction, which takes CorrelationTicket objects that have no field
    # capable of carrying it.
    labels = {
        row["ticket_id"]: row["event_id"]
        for row in (json.loads(line) for line in labels_path.read_text().splitlines())
    }
    return features, labels


def _ticket(row: dict) -> CorrelationTicket:
    """A Polaris row as the correlation engine's own ticket type.

    Only observable fields cross this boundary: subject, body, time, reported category.
    `event_type`, `topic`, `priority` and `routing` are labels and live in the other file.
    """
    subject = (row.get("subject") or "").strip()
    body = (row.get("body") or "").strip()
    return CorrelationTicket(
        id=row["ticket_id"],
        title=subject or body[:80] or "untitled report",
        description=body,
        created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
        # The reporter's own category, which is an observation rather than a verdict.
        service_id=row.get("reported_category"),
        reported_by=None,
    )


def build_examples(
    directory: Path, *, seed: int = 20260901, max_per_event: int = 400
) -> tuple[list[PairwiseExample], DatasetSummary]:
    """Candidate-level examples, constructed chronologically.

    Every positive is (arriving ticket, candidate of *earlier* members from the same
    event, inside the window). Every negative pairs an arriving ticket with a candidate
    built from a *different* event at a comparable time — the plausible-but-wrong
    candidate the runtime actually has to reject.
    """
    rows, labels = _load(directory)
    rng = random.Random(seed)

    by_event: dict[str, list[dict]] = {}
    excluded: dict[str, str] = {}
    for row in rows:
        event = labels.get(row["ticket_id"])
        if not event or event in ("none", ""):
            continue
        if event.startswith("launch_"):
            excluded.setdefault(
                event,
                "product launch spanning months; a rollout campaign is not an incident "
                "and training on it would teach topical grouping",
            )
            continue
        by_event.setdefault(event, []).append(row)

    for event, group in by_event.items():
        group.sort(key=lambda row: row["created_at"])

    events = sorted(by_event)
    examples: list[PairwiseExample] = []
    positives = negatives = hard = 0

    for event in events:
        tickets = [_ticket(row) for row in by_event[event]]
        made = 0

        for index, arriving in enumerate(tickets):
            if made >= max_per_event or index == 0:
                continue
            # The candidate as it stood before this ticket arrived: earlier members only,
            # inside the window, capped at a realistic candidate size.
            prior = [
                member
                for member in tickets[:index]
                if arriving.created_at - member.created_at <= POSITIVE_WINDOW
            ][-MAX_CANDIDATE_MEMBERS:]
            if not prior:
                continue

            examples.append(
                PairwiseExample(
                    features=extract(arriving, prior),
                    label=1,
                    group=event,
                    arriving_id=arriving.id,
                    candidate_id=f"{event}:{prior[0].id}",
                )
            )
            positives += 1
            made += 1

            # One negative per positive, with the time features held **identical**.
            #
            # This took three attempts and each failure was caught by reading the learned
            # coefficients rather than by accuracy, which stayed high throughout:
            #
            #   1. Unaligned sampling — Polaris outages sit years apart, so the model
            #      learned `within_active_window` (+3.03) and scored a meaningless +0.97
            #      separation. It had learned "2024 or 2026".
            #   2. Aligning the wrong candidate's last member to the arriving time gave
            #      negatives a zero-minute gap while positives had one to ninety, so the
            #      model learned the inverse: `time_score_nearest` at -5.68, meaning
            #      *closer in time is less likely the same incident*. Nonsense, and the
            #      sign is what revealed it.
            #
            # So the negative candidate is shifted to reproduce the positive's gap
            # structure exactly. Every time feature is then identical between the two, and
            # the only thing left to discriminate on is content. That is precisely the
            # question M17 left open, and it is why this construction is disclosed in the
            # dataset metadata rather than buried.
            other = rng.choice([name for name in events if name != event])
            pool = [_ticket(row) for row in by_event[other]]
            anchor = rng.randrange(len(pool))
            wrong_raw = pool[max(0, anchor - len(prior)) : anchor]
            if len(wrong_raw) != len(prior):
                continue
            wrong = [
                member.model_copy(update={"created_at": match.created_at})
                for member, match in zip(wrong_raw, prior, strict=True)
            ]
            features = extract(arriving, wrong)
            examples.append(
                PairwiseExample(
                    features=features,
                    label=0,
                    group=event,
                    arriving_id=arriving.id,
                    candidate_id=f"{other}:{wrong[0].id}",
                )
            )
            negatives += 1
            # A negative is "hard" when the deterministic signals do not already refuse it.
            if not features["service_conflict"] and not features["issue_conflict"]:
                hard += 1

    summary = DatasetSummary(
        version=DATASET_VERSION,
        events_used=tuple(events),
        events_excluded=excluded,
        positives=positives,
        negatives=negatives,
        hard_negatives=hard,
    )
    return examples, summary


def grouped_split(
    examples: Sequence[PairwiseExample], *, seed: int = 20260901
) -> tuple[list[PairwiseExample], list[PairwiseExample], list[PairwiseExample]]:
    """Train / dev / held-out, split by event so no event crosses a boundary.

    Splitting by pair would put tickets from one outage on both sides and produce a score
    that measures memorisation. With seven groups the split is coarse — roughly 4/1/2 —
    and that is a real limit on what any number here can claim.
    """
    events = sorted({example.group for example in examples if example.group})
    rng = random.Random(seed)
    shuffled = list(events)
    rng.shuffle(shuffled)

    held_out = set(shuffled[:2])
    dev = set(shuffled[2:3])
    train = set(shuffled[3:])

    def take(names: set[str]) -> list[PairwiseExample]:
        return [example for example in examples if example.group in names]

    return take(train), take(dev), take(held_out)


def iter_feature_rows(examples: Sequence[PairwiseExample]) -> Iterator[list[float]]:
    for example in examples:
        yield example.vector()
