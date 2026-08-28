"""Score action policy on recorded investigator recommendations.

Writes `golden-policy-replay.json`: policy-v1 and policy-v2 over the identical set of
investigator-v2 recommendations, so the only variable is the policy. Calls no model.

    uv run --group semantic python scripts/evaluate_policy_replay.py
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.embeddings import EmbeddingCache, LocalEmbeddingProvider  # noqa: E402
from app.investigation import load_operations  # noqa: E402
from app.retrieval import HistoricalIndex, load_corpus  # noqa: E402
from evaluation.policy_replay import (  # noqa: E402
    RECORDED_V2_ABSTAINED,
    RECORDED_V2_RUN,
    replay,
)

EVAL_VERSION = "investigation-eval-v2"
OUTPUT = "golden-policy-replay.json"


def main() -> int:
    settings = get_settings()
    operations = load_operations(settings.fixtures_dir)
    provider = LocalEmbeddingProvider()
    index = HistoricalIndex(
        provider, EmbeddingCache(settings.embeddings_cache_dir, provider)
    )
    index.build(load_corpus(settings.fixtures_dir, settings.itsm_processed_dir))

    base = Path(settings.investigation_evals_dir)
    cases = json.loads((base / "investigation_cases_v2.json").read_text())["records"]
    labels = {
        record["case_id"]: record
        for record in json.loads(
            (base / "investigation_labels_v2.json").read_text()
        )["records"]
    }
    expected = sum(
        1
        for case_id, record in labels.items()
        if record["allowed_remediation"] and case_id in RECORDED_V2_RUN
    )

    versions = []
    for policy_version in ("action-policy-v1", "action-policy-v2"):
        summary = replay(
            cases=cases,
            labels=labels,
            operations=operations,
            index=index,
            recorded=RECORDED_V2_RUN,
            abstained=RECORDED_V2_ABSTAINED,
            policy_version=policy_version,
        )
        rates = summary.rates(expected_cases=expected)
        versions.append(
            {
                "policy_version": policy_version,
                "recommendations": summary.recommendations,
                "eligible": len(summary.eligible_total),
                "unsafe_allowed": [o.case_id for o in summary.unsafe_allowed],
                "valid_blocked": [o.case_id for o in summary.valid_blocked],
                "metrics": rates,
                "cases": [
                    {
                        "case_id": o.case_id,
                        "action_type": o.action_type,
                        "eligible": o.eligible,
                        "decision": o.decision,
                        "failed_checks": list(o.failed_checks),
                        "expected_actions": list(o.expected_actions),
                        "unsafe_if_recommended": o.unsafe,
                    }
                    for o in summary.outcomes
                ],
            }
        )
        print(f"\n=== {policy_version} ===")
        for outcome in summary.outcomes:
            print(
                f"  {outcome.case_id} {outcome.action_type:20} "
                f"{'ELIGIBLE' if outcome.eligible else 'BLOCKED'} "
                f"{','.join(outcome.failed_checks) or ''}"
            )
        for name, value in rates.items():
            print(f"  {name}: {'n/a' if value is None else f'{value:.1%}'}")

    report = {
        "suite": "policy-replay",
        "investigator_version": "investigation-v2",
        "eval_version": EVAL_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "note": (
            "Recorded investigator-v2 recommendations replayed through two policy "
            "versions. No model was called. Citations are reconstructed from the "
            "deterministic evidence registry — the recorded artifact stored action types "
            "but not cited ids — with the recommendation citing every available item, "
            "which is the most generous input policy can receive. Eligibility here is "
            "therefore an upper bound on what the real citation could have achieved."
        ),
        "expected_remediation_cases": expected,
        "versions": versions,
    }
    path = base / OUTPUT
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
