"""Run the triage evaluation suites.

Usage (from apps/api):
    uv run python scripts/evaluate_triage.py --suite golden
    uv run python scripts/evaluate_triage.py --suite polaris [--limit N]

The golden report is committed (we authored every case). The Polaris report is written
under data/processed/, which is gitignored, and carries no source text.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.models import EvalReport  # noqa: E402
from evaluation.runner import run_golden, run_polaris  # noqa: E402
from ingestion.errors import IngestionError  # noqa: E402
from ingestion.io import write_json  # noqa: E402
from ingestion.paths import POLARIS_PROCESSED_DIR, PROCESSED_DIR, REPO_ROOT  # noqa: E402

GOLDEN_DIR = REPO_ROOT / "data" / "evals" / "golden"
GOLDEN_REPORT_DIR = REPO_ROOT / "data" / "evals" / "triage"
POLARIS_REPORT_DIR = PROCESSED_DIR / "evals"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("golden", "polaris", "all"), default="all")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    reports: list[tuple[EvalReport, Path]] = []
    try:
        if args.suite in ("golden", "all"):
            report = run_golden(GOLDEN_DIR)
            reports.append((report, GOLDEN_REPORT_DIR / f"golden-{report.version}.json"))
        if args.suite in ("polaris", "all"):
            report = run_polaris(POLARIS_PROCESSED_DIR, limit=args.limit, seed=args.seed)
            reports.append(
                (report, POLARIS_REPORT_DIR / f"polaris-{report.version}.json")
            )
    except IngestionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    for report, path in reports:
        write_json(path, report)
        _print(report, path)
    return 0


def _print(report: EvalReport, path: Path) -> None:
    print(f"\n{report.suite} — {report.version} ({report.case_count} cases)")
    for metric in report.metrics:
        line = (
            f"  {metric.name:<11} {metric.accuracy:6.1%}  "
            f"({metric.correct}/{metric.total}, abstained {metric.abstained})"
        )
        if metric.majority_baseline is not None:
            line += f"  majority-class baseline {metric.majority_baseline:.1%}"
        print(line)

    if report.confusion:
        print("  most common errors:")
        for cell in report.confusion[:8]:
            print(f"    {cell.expected} -> {cell.predicted}  x{cell.count}")

    print(f"  failures: {len(report.failures)}")
    print(f"  written: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
