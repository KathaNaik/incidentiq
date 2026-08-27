"""Run the correlation evaluation suites.

Usage (from apps/api):
    uv run python scripts/evaluate_correlation.py --suite golden
    uv run python scripts/evaluate_correlation.py --suite polaris [--limit N]

The golden report is committed (we authored every ticket in it). The Polaris report is
written under data/processed/, which is gitignored, and carries no ticket text.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.correlation.semantic import default_similarity  # noqa: E402
from app.embeddings import EmbeddingError  # noqa: E402
from evaluation.comparison import VersionComparison, compare_golden  # noqa: E402
from evaluation.correlation import run_golden, run_polaris  # noqa: E402
from evaluation.models import EvalReport  # noqa: E402
from ingestion.errors import IngestionError  # noqa: E402
from ingestion.io import write_json  # noqa: E402
from ingestion.paths import POLARIS_PROCESSED_DIR, PROCESSED_DIR, REPO_ROOT  # noqa: E402

GOLDEN_DIR = REPO_ROOT / "data" / "evals" / "correlation"
POLARIS_REPORT_DIR = PROCESSED_DIR / "evals"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("golden", "polaris", "all"), default="all")
    parser.add_argument(
        "--mode",
        choices=("deterministic", "semantic", "both"),
        default="deterministic",
        help="which correlation version to run; 'both' also writes a comparison",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    similarity = None
    if args.mode in ("semantic", "both"):
        similarity = default_similarity(get_settings().embeddings_cache_dir)

    reports: list[tuple[EvalReport, Path]] = []
    try:
        if args.suite in ("golden", "all"):
            if args.mode in ("deterministic", "both"):
                report = run_golden(GOLDEN_DIR)
                reports.append((report, GOLDEN_DIR / f"golden-{report.version}.json"))
            if args.mode in ("semantic", "both"):
                report = run_golden(GOLDEN_DIR, similarity)
                reports.append((report, GOLDEN_DIR / f"golden-{report.version}.json"))
        if args.suite in ("polaris", "all"):
            if args.mode in ("deterministic", "both"):
                report = run_polaris(POLARIS_PROCESSED_DIR, limit=args.limit)
                reports.append(
                    (report, POLARIS_REPORT_DIR / f"correlation-polaris-{report.version}.json")
                )
            if args.mode in ("semantic", "both"):
                report = run_polaris(
                    POLARIS_PROCESSED_DIR, limit=args.limit, similarity=similarity
                )
                reports.append(
                    (report, POLARIS_REPORT_DIR / f"correlation-polaris-{report.version}.json")
                )

        if args.mode == "both" and args.suite in ("golden", "all"):
            comparison = compare_golden(GOLDEN_DIR, similarity)
            write_json(
                GOLDEN_DIR / f"comparison-{comparison.candidate_version}.json", comparison
            )
            _print_comparison(comparison)
    except (IngestionError, EmbeddingError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    for report, path in reports:
        write_json(path, report)
        _print(report, path)
    return 0


def _print(report: EvalReport, path: Path) -> None:
    print(f"\n{report.suite} — {report.version} ({report.case_count} tickets)")
    for metric in report.metrics:
        print(
            f"  {metric.name:<21} {metric.accuracy:7.1%}  "
            f"({metric.correct}/{metric.total})"
        )
    for note in report.notes:
        print(f"  note: {note}")
    print(f"  failures listed: {len(report.failures)}")
    print(f"  written: {path}")


def _print_comparison(comparison: VersionComparison) -> None:
    print(
        f"\ncomparison — {comparison.baseline_version} vs "
        f"{comparison.candidate_version} ({comparison.ticket_count} tickets)"
    )
    print(f"  {'metric':<21} {'baseline':>9} {'semantic':>9} {'delta':>9}")
    for metric in comparison.metrics:
        print(
            f"  {metric.name:<21} {metric.baseline:9.1%} {metric.candidate:9.1%} "
            f"{metric.delta:+9.1%}"
        )
    counts: dict[str, int] = {}
    for example in comparison.slices:
        counts[example.kind] = counts.get(example.kind, 0) + 1
    for kind, count in sorted(counts.items()):
        print(f"  {kind}: {count}")


if __name__ == "__main__":
    raise SystemExit(main())
