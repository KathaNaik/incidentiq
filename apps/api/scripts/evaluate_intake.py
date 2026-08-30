"""Score incremental intake correlation on the authored online set.

    uv run python scripts/evaluate_intake.py                  # deterministic
    uv run --group semantic python scripts/evaluate_intake.py --semantic
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from evaluation.intake import evaluate_case, load_online_cases, run_online_evaluation  # noqa: E402
from ingestion.io import write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semantic", action="store_true", help="use semantic correlation")
    args = parser.parse_args()

    settings = get_settings()
    directory = Path(settings.evals_dir).parent / "intake"

    similarity = None
    if args.semantic:
        from app.correlation.semantic import default_similarity

        similarity = default_similarity(settings.embeddings_cache_dir)

    report = run_online_evaluation(directory, similarity)
    path = directory / f"golden-intake-{report.version}.json"
    write_json(path, report)

    print(f"\n{report.suite} — {report.version} ({report.case_count} cases)")
    for metric in report.metrics:
        print(f"  {metric.name:<30} {metric.accuracy:7.1%}  ({metric.correct}/{metric.total})")
    print()
    for case in load_online_cases(directory):
        outcome = evaluate_case(case, similarity)
        mark = "OK  " if outcome.correct else "MISS"
        print(
            f"  {mark} {outcome.case_id}  expected {outcome.expected:18} "
            f"got {outcome.actual:18} {outcome.detail}"
        )
    print(f"\n  written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
