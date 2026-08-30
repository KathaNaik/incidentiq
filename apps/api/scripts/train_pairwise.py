"""Train and evaluate the pairwise incident-identity model.

    uv run --group pairwise python scripts/train_pairwise.py

Needs the gitignored Polaris copy from `scripts/download_polaris.py` +
`scripts/preprocess_polaris.py`. No Polaris content is written to the repository — only
the fitted model and aggregate metrics.
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.pairwise.dataset import build_examples, grouped_split  # noqa: E402
from app.pairwise.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION  # noqa: E402
from app.pairwise.model import (  # noqa: E402
    PAIRWISE_VERSION,
    THRESHOLD_RULE,
    save,
    select_threshold,
    train,
)


def evaluate(trained, examples, label: str) -> dict:
    """Ordering and separation, which is what M17 showed cosine could not do."""
    scored = [(trained.score(e.features), e) for e in examples]
    positives = sorted(score for score, e in scored if e.label == 1)
    hard = sorted(
        score
        for score, e in scored
        if e.label == 0
        and not e.features["service_conflict"]
        and not e.features["issue_conflict"]
    )
    easy = sorted(
        score
        for score, e in scored
        if e.label == 0
        and (e.features["service_conflict"] or e.features["issue_conflict"])
    )

    wins = sum(1 for p in positives for n in hard if p > n)
    comparisons = len(positives) * len(hard)
    above = sum(1 for score in positives if score >= trained.threshold)
    merges = sum(1 for score in hard if score >= trained.threshold)

    return {
        "split": label,
        "examples": len(examples),
        "positives": len(positives),
        "hard_negatives": len(hard),
        "easy_negatives": len(easy),
        "positive_min": round(positives[0], 4) if positives else None,
        "positive_max": round(positives[-1], 4) if positives else None,
        "hard_negative_min": round(hard[0], 4) if hard else None,
        "hard_negative_max": round(hard[-1], 4) if hard else None,
        "separation_margin": round(positives[0] - hard[-1], 4)
        if positives and hard
        else None,
        "ordering_accuracy": round(wins / comparisons, 4) if comparisons else None,
        "recall_at_threshold": round(above / len(positives), 4) if positives else None,
        "hard_negative_false_merges": merges,
        "hard_negative_false_merge_rate": round(merges / len(hard), 4) if hard else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-per-event", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260901)
    args = parser.parse_args()

    settings = get_settings()
    polaris = Path(settings.itsm_processed_dir).parent / "polaris"

    started = time.perf_counter()
    examples, summary = build_examples(
        polaris, seed=args.seed, max_per_event=args.max_per_event
    )
    train_set, dev_set, held_out = grouped_split(examples, seed=args.seed)

    print(f"dataset {summary.version}")
    print(f"  {summary.total} examples  (+{summary.positives} / -{summary.negatives})")
    print(f"  positive rate {summary.positive_rate}   hard negatives {summary.hard_negatives}")
    print(f"  events used {len(summary.events_used)}, excluded {len(summary.events_excluded)} launches")
    print(f"  grouped split — train {len({e.group for e in train_set})} / "
          f"dev {len({e.group for e in dev_set})} / held-out {len({e.group for e in held_out})} events")
    overlap = ({e.group for e in train_set} | {e.group for e in dev_set}) & {
        e.group for e in held_out
    }
    print(f"  event overlap across splits: {overlap or 'none'}")
    print(f"  features: {len(FEATURE_NAMES)} ({FEATURE_SCHEMA_VERSION})\n")

    results = {}
    for model_kind in ("logistic", "tree"):
        fitted = train(train_set, model=model_kind, seed=args.seed)
        threshold, selection = select_threshold(fitted, dev_set)
        fitted.threshold = threshold
        dev = evaluate(fitted, dev_set, "development")
        results[model_kind] = (fitted, selection, dev)

        print(f"=== {fitted.model_class} ===")
        print(f"  threshold {threshold}  ({selection['rule']})")
        print(f"  dev  positives {dev['positive_min']}–{dev['positive_max']}  "
              f"hard negatives {dev['hard_negative_min']}–{dev['hard_negative_max']}")
        print(f"  dev  separation {dev['separation_margin']:+}  ordering {dev['ordering_accuracy']}")
        print(f"  dev  recall@threshold {dev['recall_at_threshold']}  "
              f"hard false merges {dev['hard_negative_false_merges']}\n")

    # Selection on development evidence only.
    chosen_kind = max(
        results,
        key=lambda kind: (
            results[kind][2]["ordering_accuracy"] or 0,
            results[kind][2]["recall_at_threshold"] or 0,
        ),
    )
    chosen, selection, dev = results[chosen_kind]
    print(f"selected on development evidence: {chosen.model_class}\n")

    coefficients = chosen.coefficients()
    if coefficients:
        print("  strongest learned weights (sanity check):")
        for name, value in coefficients[:8]:
            print(f"    {value:+8.3f}  {name}")
        print()

    held = evaluate(chosen, held_out, "held_out")
    print("=== held-out (one run, after freezing model and threshold) ===")
    print(f"  positives {held['positive_min']}–{held['positive_max']}  "
          f"hard negatives {held['hard_negative_min']}–{held['hard_negative_max']}")
    print(f"  separation {held['separation_margin']:+}  ordering {held['ordering_accuracy']}")
    print(f"  recall@threshold {held['recall_at_threshold']}  "
          f"hard false merges {held['hard_negative_false_merges']}")

    import sklearn

    chosen.metadata = {
        "version": PAIRWISE_VERSION,
        "dataset_version": summary.version,
        "dataset_note": (
            "Polaris outage events only; product launches excluded. Positives are drawn "
            "inside the correlation window so a pair resembles a runtime decision. Only "
            f"{len(summary.events_used)} event groups exist, so the effective sample size "
            "for generalisation is small however many pairs are produced."
        ),
        "events_used": list(summary.events_used),
        "events_excluded": summary.events_excluded,
        "positives": summary.positives,
        "negatives": summary.negatives,
        "hard_negatives": summary.hard_negatives,
        "split_seed": args.seed,
        "train_events": sorted({e.group for e in train_set}),
        "dev_events": sorted({e.group for e in dev_set}),
        "held_out_events": sorted({e.group for e in held_out}),
        "threshold_selection": selection,
        "sklearn_version": sklearn.__version__,
        "trained_at": datetime.now(UTC).isoformat(),
        "development": dev,
        "held_out": held,
        "coefficients": [{"feature": n, "weight": round(v, 4)} for n, v in coefficients],
        "candidates_compared": {
            kind: results[kind][2] for kind in results
        },
    }

    artifact = Path(settings.evals_dir).parent.parent / "models" / "pairwise-correlation-v1.joblib"
    digest = save(chosen, artifact)

    # A sanitised record for the repository. The fitted artifact stays gitignored because
    # it was trained on the CC BY-SA Polaris corpus and this project flags rather than
    # distributes anything adapted from it. Polaris event identifiers are replaced with
    # counts here: the metrics are ours, the identifiers are the dataset's.
    published = {
        "suite": "pairwise-correlation",
        "version": PAIRWISE_VERSION,
        "model_class": chosen.model_class,
        "feature_schema": FEATURE_SCHEMA_VERSION,
        "feature_count": len(FEATURE_NAMES),
        "feature_names": list(FEATURE_NAMES),
        "sklearn_version": sklearn.__version__,
        "artifact_sha256": digest,
        "threshold": chosen.threshold,
        "threshold_selection": selection,
        "dataset": {
            "source": "polaris outage events (external, CC BY-SA, never committed)",
            "note": chosen.metadata["dataset_note"],
            "events_used": len(summary.events_used),
            "events_excluded_launches": len(summary.events_excluded),
            "positives": summary.positives,
            "negatives": summary.negatives,
            "hard_negatives": summary.hard_negatives,
            "negatives_time_aligned": True,
            "split_events": {
                "train": len({e.group for e in train_set}),
                "development": len({e.group for e in dev_set}),
                "held_out": len({e.group for e in held_out}),
            },
        },
        "development": dev,
        "held_out": held,
        "coefficients": chosen.metadata["coefficients"],
        "candidates_compared": chosen.metadata["candidates_compared"],
        "caveat": (
            "Eight event groups. The grouped split is correct and mandatory, but the "
            "effective sample size for generalisation is eight however many pairs are "
            "produced. Polaris `reported_category` is also not a Northstar service, so "
            "transfer to the authored cases is not guaranteed — the learned "
            "`service_conflict` weight is positive, which is domain nonsense and is "
            "evidence of exactly that mismatch."
        ),
    }
    metrics_path = Path(settings.evals_dir).parent / "intake" / "golden-pairwise-training.json"
    metrics_path.write_text(json.dumps(published, indent=2) + "\n")
    print(f"  metrics  {metrics_path}")
    print(f"\n  artifact {artifact}")
    print(f"  sha256   {digest[:16]}…")
    print(f"  trained in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
