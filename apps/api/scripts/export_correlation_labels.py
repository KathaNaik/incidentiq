"""Export operator correlation decisions as training data.

    uv run --group pairwise python scripts/export_correlation_labels.py

Admin tooling rather than a runtime endpoint: this is a dataset operation, and the product
surface should not talk about training labels at all.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.review import ReviewService, ReviewStatus  # noqa: E402
from app.review.export import build_export, write_jsonl  # noqa: E402


def main() -> int:
    settings = get_settings()
    reviews = ReviewService().all_reviews()
    result = build_export(reviews)

    statuses = Counter(review.status.value for review in reviews)
    print("correlation reviews")
    for name in ("pending", "confirmed", "rejected", "stale"):
        print(f"  {name:10} {statuses.get(name, 0)}")

    print(f"\nexportable labels: {result.count}")
    print(f"  confirmed (same incident)     {result.confirmed}")
    print(f"  rejected  (different incident) {result.rejected_label}")
    print(f"  positive rate {result.positive_rate}")

    if result.rejected:
        print(f"\nexcluded {len(result.rejected)}:")
        for record in result.rejected:
            print(f"  {record.review_id}: {record.reason}")

    sizes = Counter(
        len((r.candidate_snapshot or {}).get("members") or [])
        for r in reviews
        if r.decided and r.status is not ReviewStatus.STALE
    )
    services = Counter(
        (r.candidate_snapshot or {}).get("service_id")
        for r in reviews
        if r.decided and r.status is not ReviewStatus.STALE
    )
    reasons = Counter(r.decision_reason for r in reviews if r.decision_reason)
    print(f"\n  candidate sizes {dict(sorted(sizes.items()))}")
    print(f"  services        {dict(services)}")
    print(f"  reasons         {dict(reasons)}")

    path = Path(settings.evals_dir).parent / "labels" / "northstar-correlation-labels.jsonl"
    header = write_jsonl(result, path)
    print(f"\n  written {path}")
    print(f"  schema  {header['schema_version']} / features {header['feature_schema']}")

    # Deliberately not a hard gate — a threshold invented here would be arbitrary. The
    # judgement is stated so nobody trains on a handful of rows by accident.
    print(
        "\n  NOT model-ready. A supervised fallback should not be retrained until there "
        "are enough independent labels to support a grouped train/dev/test split with "
        "positives and hard negatives across several services and mechanisms. "
        f"There are currently {result.count}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
