"""Phase 1 embedding bake-off: does any model rank same-incident pairs above conflicts?

    uv run --group semantic python scripts/run_bakeoff.py

Downloads each model on first use. Writes `golden-embedding-bakeoff.json`.
"""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.embeddings.registry import MODELS  # noqa: E402
from evaluation.bakeoff import build_pairs, score_pairs  # noqa: E402


def main() -> int:
    settings = get_settings()
    directory = Path(settings.evals_dir).parent / "intake"
    pairs = build_pairs(directory)

    print(f"pair set: {len(pairs)} pairs from the authored online cases")
    print(f"  {sum(1 for p in pairs if p.kind == 'positive')} genuine paraphrases")
    print(f"  {sum(1 for p in pairs if p.kind == 'near_duplicate')} near-duplicate (anchor)")
    print(f"  {sum(1 for p in pairs if p.is_dangerous)} dangerous negatives\n")

    results = []
    for spec in MODELS.values():
        started = time.perf_counter()
        result = score_pairs(spec, pairs, settings.embeddings_cache_dir)
        elapsed = time.perf_counter() - started
        summary = result.summary()
        summary["scoring_seconds"] = round(elapsed, 2)
        summary["size_gb"] = spec.size_gb
        results.append(summary)

        print(f"=== {spec.id}  ({spec.model_name}, {spec.dimension}d, {spec.size_gb}GB) ===")
        print(f"  paraphrases       {summary['positive_min']:.4f} – {summary['positive_max']:.4f}"
              f"   (median {summary['positive_median']:.4f})")
        print(f"  dangerous negs    {summary['dangerous_min']:.4f} – {summary['dangerous_max']:.4f}"
              f"   (median {summary['dangerous_median']:.4f})")
        print(f"  near-duplicate    {summary['near_duplicate_min']:.4f} – {summary['near_duplicate_max']:.4f}")
        margin = summary["separation_margin"]
        verdict = "SEPARABLE" if margin > 0 else "NOT SEPARABLE"
        print(f"  separation margin {margin:+.4f}   {verdict}")
        print(f"  ordering accuracy {summary['ordering_accuracy']:.1%} "
              f"({summary['ordering_wins']}/{summary['ordering_comparisons']} comparisons)")
        print(f"  scored in {elapsed:.1f}s\n")

    report = {
        "suite": "embedding-bakeoff",
        "version": "bakeoff-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "note": (
            "Phase 1: raw pair ordering. The question is whether a model ranks genuine "
            "same-incident paraphrases above pairs that must never merge. Separation "
            "margin is min(paraphrase) - max(dangerous negative); a negative margin means "
            "no single threshold separates the slice and threshold tuning cannot help. "
            "Average cosine is deliberately not the headline — a model that scores "
            "everything higher has learned nothing about incident identity. "
            "Pairs are drawn from the authored M16 online cases, not written for this "
            "experiment. Embedding text is unchanged from M16, so the only variable is "
            "the model."
        ),
        "unsupported": {
            "Alibaba-NLP/gte-modernbert-base": (
                "not available through fastembed; needs PyTorch and a Transformers "
                "version with ModernBERT support — multiple gigabytes to answer a "
                "question two supported models can answer"
            ),
            "BAAI/bge-m3": "not available through fastembed",
        },
        "pairs": [
            {"id": p.id, "kind": p.kind, "note": p.note} for p in pairs
        ],
        "models": results,
    }
    path = directory / "golden-embedding-bakeoff.json"
    path.write_text(json.dumps(report, indent=2) + "\n")

    print("=" * 68)
    print(f"{'model':12}{'paraphrase':>22}{'dangerous':>22}{'margin':>10}")
    for summary in results:
        print(
            f"{summary['model_id']:12}"
            f"{summary['positive_min']:.4f}–{summary['positive_max']:.4f}".rjust(22)
            + f"{summary['dangerous_min']:.4f}–{summary['dangerous_max']:.4f}".rjust(22)
            + f"{summary['separation_margin']:+.4f}".rjust(10)
        )
    print(f"\nwritten: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
