"""Evaluate historical incident retrieval.

Usage (from apps/api):
    uv run --group semantic python scripts/evaluate_retrieval.py [--limit N] [--no-rerank]

The report is committed — it carries metrics, family ids and our own authored cases, but
no text from the external corpus.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.embeddings import EmbeddingCache, EmbeddingError, LocalEmbeddingProvider  # noqa: E402
from app.retrieval import CorpusError, HistoricalIndex, load_corpus  # noqa: E402
from evaluation.models import EvalReport  # noqa: E402
from evaluation.retrieval import run_authored_demo, run_family_evaluation  # noqa: E402
from ingestion.io import write_json  # noqa: E402

CASES_FILE = "northstar_retrieval_cases.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="score on semantic similarity alone, to measure what reranking adds",
    )
    parser.add_argument(
        "--title-only",
        action="store_true",
        help="build queries from the title alone — the harder, terser slice",
    )
    args = parser.parse_args()

    settings = get_settings()
    try:
        records = load_corpus(settings.fixtures_dir, settings.itsm_processed_dir)
        provider = LocalEmbeddingProvider()
        index = HistoricalIndex(
            provider, EmbeddingCache(settings.embeddings_cache_dir, provider)
        )
        index.build(records)

        report = run_family_evaluation(
            index,
            records,
            limit=args.limit,
            rerank=not args.no_rerank,
            title_only=args.title_only,
        )
        demo = run_authored_demo(
            index, settings.retrieval_evals_dir / CASES_FILE
        )
    except (CorpusError, EmbeddingError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    suffix = ("-no-rerank" if args.no_rerank else "") + (
        "-title-only" if args.title_only else ""
    )
    path = settings.retrieval_evals_dir / f"golden-{report.version}{suffix}.json"
    write_json(path, report)
    _print(report, demo, path)
    return 0


def _print(report: EvalReport, demo: tuple[dict, ...], path: Path) -> None:
    print(f"\n{report.suite} — {report.version} ({report.case_count} queries)")
    for metric in report.metrics:
        line = f"  {metric.name:<10} {metric.accuracy:7.1%}  ({metric.correct}/{metric.total})"
        if metric.majority_baseline is not None:
            line += f"  random baseline {metric.majority_baseline:.1%}"
        print(line)
    for note in report.notes:
        print(f"  note: {note}")

    print("\n  authored Northstar cases:")
    for case in demo:
        rank = case["rank"]
        expected = case["expected"] or "(no precedent expected)"
        state = f"rank {rank}" if rank else "not in top 5"
        print(
            f"    {case['case_id']}  expected {expected:<14} {state:<14} "
            f"top score {case['top_score']:.3f}"
        )
    print(f"\n  written: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
