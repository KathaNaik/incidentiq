"""Evaluate the AI investigator, and the retrieval-only baseline it must beat.

Usage (from apps/api):
    uv run --group semantic python scripts/evaluate_investigation.py --baseline
    uv run --group semantic python scripts/evaluate_investigation.py --model

`--baseline` needs no credentials. `--model` calls the configured OpenAI model and
requires OPENAI_API_KEY; without one it exits with a clear message rather than
producing numbers.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.embeddings import EmbeddingCache, EmbeddingError, LocalEmbeddingProvider  # noqa: E402
from app.investigation import (  # noqa: E402
    InvestigationModelError,
    OpenAIInvestigationModel,
    load_operations,
)
from app.retrieval import HistoricalIndex, load_corpus  # noqa: E402
from evaluation.investigation import run_baseline, run_investigation_evaluation  # noqa: E402
from evaluation.policy import run_policy_evaluation  # noqa: E402
from evaluation.models import EvalReport  # noqa: E402
from ingestion.io import write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval-version",
        default="v1",
        choices=["v1", "v2", "v3"],
        help="which held-out set; v3 supplies temporal evidence (default: v1)",
    )
    parser.add_argument("--baseline", action="store_true", help="run the retrieval-only baseline")
    parser.add_argument("--model", action="store_true", help="run the AI investigator")
    parser.add_argument(
        "--policy", action="store_true", help="run the deterministic action-policy suite"
    )
    parser.add_argument(
        "--prompt", default="investigation-v1", help="investigator prompt version"
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="run the development set instead of the held-out golden set",
    )
    args = parser.parse_args()
    if not any((args.baseline, args.model, args.policy)):
        args.baseline = True

    settings = get_settings()
    directory = settings.investigation_evals_dir

    try:
        operations = load_operations(settings.fixtures_dir)
        provider = LocalEmbeddingProvider()
        index = HistoricalIndex(
            provider, EmbeddingCache(settings.embeddings_cache_dir, provider)
        )
        index.build(load_corpus(settings.fixtures_dir, settings.itsm_processed_dir))
    except (EmbeddingError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    reports: list[tuple[EvalReport, Path]] = []
    if args.policy:
        report = run_policy_evaluation(operations)
        reports.append(
            (report, settings.policy_evals_dir / f"golden-{report.version}.json")
        )

    if args.baseline:
        report = run_baseline(directory, operations, index)
        reports.append((report, directory / f"golden-{report.version}.json"))

    if args.model:
        try:
            report = run_investigation_evaluation(
                directory,
                operations,
                index,
                OpenAIInvestigationModel(
                    settings.investigation_model, settings.openai_api_key
                ),
                prompt_version=args.prompt,
                eval_version=args.eval_version,
                dev=args.dev,
            )
        except InvestigationModelError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        suffix = "dev" if args.dev else "golden"
        # The filename carries the eval version as well as the prompt version. A run is
        # identified by both — the same prompt over different evidence is a different
        # measurement, and overwriting one with the other would lose that.
        stem = f"{suffix}-{report.version}"
        if args.eval_version != "v1" and not args.dev:
            stem += f"-eval-{args.eval_version}"
        reports.append((report, directory / f"{stem}.json"))

    for report, path in reports:
        write_json(path, report)
        print(f"\n{report.suite} — {report.version} ({report.case_count} cases)")
        for metric in report.metrics:
            print(
                f"  {metric.name:<30} {metric.accuracy:7.1%}  "
                f"({metric.correct}/{metric.total})"
            )
        for note in report.notes:
            print(f"  note: {note}")
        print(f"  failures listed: {len(report.failures)}")
        print(f"  written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
