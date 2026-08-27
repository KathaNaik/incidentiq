"""Historical retrieval evaluation.

**What counts as relevant.** A historical incident is relevant to a query if it shares
the query's *root-cause family* — the same underlying technical failure, however
differently it was reported. The external corpus supplies this: its record ids carry a
family prefix (`INC-ALP-0042`), and the families are coherent — `INC-ALP` is "cached
mobile credentials cause an AD lockout after a password reset", `INC-CES` is "expired TLS
certificate with a stale load-balancer chain", and so on. Same cause, ~50 different
tellings each.

That prefix is ground truth and nothing else: it is absent from the indexed text, absent
from the query text, and never reaches a score. Deliberately *not* used as relevance:
priority, which says nothing about whether one incident is precedent for another.

**Why this is not self-retrieval.** Each query is built from one record's reported
symptoms, and that record is excluded from its own search. A hit only counts if a
*different* record from the same family ranks in the top K — which means matching a
failure pattern across different wording, not finding the document you started from.

**The number to beat.** Families average ~53 records in a corpus of 751, so a system
choosing at random would score roughly 30% Recall@5. That baseline is computed from the
actual corpus and reported next to the result.
"""

from datetime import UTC, datetime
from pathlib import Path

from app.correlation.entities import extract_entities
from app.retrieval import (
    RETRIEVAL_VERSION,
    HistoricalIncident,
    HistoricalIndex,
    RetrievalQuery,
)
from app.retrieval.corpus import family_of
from app.retrieval.models import Provenance
from evaluation.models import CaseFailure, EvalReport, MetricSummary

RECALL_DEPTHS = (1, 3, 5)
MAX_REPORTED = 10
# Entity kinds a real query would carry, extracted from the ticket text itself rather
# than read off the record's curated fields.
QUERY_ENTITY_KINDS = frozenset({"error_code", "http_status", "identifier", "region"})


def query_for(record: HistoricalIncident, *, title_only: bool = False) -> RetrievalQuery:
    """The query a record's *reported symptoms* would have produced.

    Title and description only. The services and observed-errors fields the corpus
    curates are not copied across — an operator writing a ticket has not curated
    anything — but identifiers appearing in the text itself are extracted, exactly as
    the runtime query builder does.

    `title_only` is the harder slice: one line, the way a terse ticket actually arrives.
    The full-text task is close to duplicate detection on this corpus (see the module
    docstring), so this is the variant that tests whether retrieval survives thin input.
    """
    if title_only:
        text = record.title.strip()
    else:
        text = f"{record.title.strip()}. {record.summary.strip()}".strip(". ")
    identifiers = tuple(
        dict.fromkeys(
            entity.value
            for entity in extract_entities(f"{record.title} {record.summary}")
            if entity.kind in QUERY_ENTITY_KINDS
        )
    )
    return RetrievalQuery(text=text, error_identifiers=identifiers)


def run_family_evaluation(
    index: HistoricalIndex,
    records: tuple[HistoricalIncident, ...],
    *,
    limit: int | None = None,
    rerank: bool = True,
    title_only: bool = False,
) -> EvalReport:
    """Leave-one-out precedent retrieval across the external corpus."""
    external = [
        record for record in records if record.provenance is Provenance.ITSM
    ]
    if not external:
        raise ValueError(
            "no external historical records; run the ITSM download and preprocess "
            "scripts first"
        )

    family_sizes: dict[str, int] = {}
    for record in external:
        family = family_of(record.id)
        family_sizes[family] = family_sizes.get(family, 0) + 1

    queries = external[:limit] if limit is not None else external

    hits_at: dict[int, int] = {depth: 0 for depth in RECALL_DEPTHS}
    reciprocal_ranks: list[float] = []
    failures: list[CaseFailure] = []

    for record in queries:
        family = family_of(record.id)
        result = index.search(
            query_for(record, title_only=title_only),
            k=max(RECALL_DEPTHS),
            exclude=frozenset({record.id}),
            rerank=rerank,
        )

        ranks = [
            hit.rank for hit in result.hits if family_of(hit.incident.id) == family
        ]
        first = min(ranks) if ranks else None
        for depth in RECALL_DEPTHS:
            if first is not None and first <= depth:
                hits_at[depth] += 1
        reciprocal_ranks.append(1.0 / first if first else 0.0)

        if first is None and len(failures) < MAX_REPORTED:
            top = result.hits[0] if result.hits else None
            failures.append(
                CaseFailure(
                    case_id=record.id,
                    metric="recall@5",
                    expected=f"family {family}",
                    predicted=(
                        f"family {family_of(top.incident.id)}" if top else None
                    ),
                    status="missed_precedent",
                    explanation=(
                        f"top hit {top.incident.id} scored {top.score:.3f} "
                        f"(similarity {top.similarity:.3f})"
                        if top
                        else "no hits"
                    ),
                    signals=tuple(
                        signal.detail for hit in result.hits[:3] for signal in hit.signals
                    ),
                    # External corpus text is not copied into a committed report.
                    text=None,
                )
            )

    total = len(queries)
    metrics = tuple(
        MetricSummary(
            name=f"recall@{depth}",
            correct=hits_at[depth],
            total=total,
            accuracy=round(hits_at[depth] / total, 4) if total else 0.0,
            majority_baseline=_random_baseline(family_sizes, len(external), depth),
        )
        for depth in RECALL_DEPTHS
    ) + (
        MetricSummary(
            name="mrr",
            correct=sum(1 for value in reciprocal_ranks if value > 0),
            total=total,
            accuracy=round(sum(reciprocal_ranks) / total, 4) if total else 0.0,
        ),
    )

    return EvalReport(
        suite="historical-retrieval",
        version=RETRIEVAL_VERSION,
        generated_at=datetime.now(UTC),
        case_count=total,
        metrics=metrics,
        confusion=(),
        failures=tuple(failures),
        notes=(
            "Relevance means same root-cause family. Family ids come from the corpus's "
            "record-id prefix and appear in no indexed text, query, or score.",
            "Leave-one-out: each query's own record is excluded, so a hit requires "
            "matching a different telling of the same failure.",
            f"Corpus: {index.size} records, {len(family_sizes)} families. "
            f"Reranking {'on' if rerank else 'off'}. "
            f"Query text: {'title only' if title_only else 'title and description'}.",
            "Caveat on this metric: the external corpus is 14 tight clusters of "
            "near-paraphrases (intra-family cosine median 0.89 against 0.63 between "
            "families), so same-family retrieval is closer to duplicate detection than "
            "to finding precedent across genuinely different incidents. The authored "
            "Northstar cases are the harder test.",
            "External corpus text does not appear in this report.",
        ),
    )


def _random_baseline(
    family_sizes: dict[str, int], corpus: int, depth: int
) -> float:
    """Chance of landing at least one same-family record in the top `depth` at random.

    Averaged over families, weighted by how many queries each contributes.
    """
    if corpus <= 1:
        return 0.0
    total_queries = sum(family_sizes.values())
    expected = 0.0
    for size in family_sizes.values():
        # Sampling `depth` records from the corpus minus the held-out one.
        miss = 1.0
        others, pool = size - 1, corpus - 1
        for step in range(depth):
            if pool - step <= 0:
                break
            miss *= max(0.0, (pool - others - step)) / (pool - step)
        expected += size * (1.0 - miss)
    return round(expected / total_queries, 4)


def run_authored_demo(
    index: HistoricalIndex, cases_path: Path
) -> tuple[dict, ...]:
    """Runs the authored Northstar retrieval scenarios.

    Small and hand-checked: these exist to show the demo path works end to end, not to
    produce a headline metric.
    """
    import json

    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    outcomes = []
    for case in payload["records"]:
        result = index.search(
            RetrievalQuery(
                text=case["query_text"],
                services=tuple(case.get("services", ())),
                error_identifiers=tuple(case.get("error_identifiers", ())),
            ),
            k=5,
        )
        ranked = [hit.incident.id for hit in result.hits]
        expected = case["expected_incident_id"]
        outcomes.append(
            {
                "case_id": case["id"],
                "expected": expected,
                "retrieved": ranked,
                "rank": ranked.index(expected) + 1 if expected in ranked else None,
                "top_score": result.hits[0].score if result.hits else 0.0,
            }
        )
    return tuple(outcomes)
