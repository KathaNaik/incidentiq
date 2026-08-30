"""The pairwise incident-identity model: training, persistence, scoring.

Small and inspectable on purpose. Logistic regression first, because its coefficients can
be read and sanity-checked against domain expectation — a model that learns "shared error
identifier means less likely the same incident" is broken however good its accuracy looks,
and only a readable model makes that visible.

**The score is `pairwise_score`, not `confidence`.** It is a logistic output on a small,
grouped, eight-event training set; calling it a confidence would imply a calibration
nobody has established.

**The model is a scorer, never the authority.** Hard conflicts, complete-link cohesion and
the M16 eligibility gate all still run, and all of them can refuse an attachment the model
scored highly. That ordering is the point: the classifier answers "does this plausibly
belong", the deterministic layer answers "would attaching it be safe".
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.pairwise.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, PairwiseExample

PAIRWISE_VERSION = "pairwise-correlation-v1"

# Threshold rule, fixed before the held-out set was touched:
#
#   the lowest threshold that produces ZERO hard-negative false positives on development
#   data, and failing that the highest-precision point available.
#
# False merges are the expensive error — they invent an incident that is not happening —
# so recall is maximised *subject to* precision on hard negatives rather than traded
# against it. 0.5 by habit would be choosing a number for no reason.
THRESHOLD_RULE = (
    "lowest development threshold with zero hard-negative false positives; "
    "recall maximised subject to that constraint"
)


class PairwiseModelError(RuntimeError):
    """The model could not be loaded or scored. Never silently downgraded."""


@dataclass
class TrainedModel:
    """A fitted model plus everything needed to explain and reproduce it."""

    estimator: Any
    scaler: Any
    threshold: float
    model_class: str
    feature_names: tuple[str, ...] = FEATURE_NAMES
    feature_schema: str = FEATURE_SCHEMA_VERSION
    version: str = PAIRWISE_VERSION
    metadata: dict = field(default_factory=dict)

    def score(self, features: dict[str, float]) -> float:
        """Same-incident score for one decision.

        Validates the schema rather than trusting the caller: a permuted vector produces
        a plausible number and a wrong answer, which is the worst kind of bug.
        """
        missing = set(self.feature_names) - set(features)
        if missing:
            raise PairwiseModelError(
                f"feature schema mismatch: missing {', '.join(sorted(missing))}"
            )
        row = [[float(features[name]) for name in self.feature_names]]
        if self.scaler is not None:
            row = self.scaler.transform(row)
        return float(self.estimator.predict_proba(row)[0][1])

    def coefficients(self) -> list[tuple[str, float]]:
        """Learned weights, largest magnitude first. Empty for a tree model."""
        raw = getattr(self.estimator, "coef_", None)
        if raw is None:
            return []
        return sorted(
            zip(self.feature_names, (float(v) for v in raw[0]), strict=True),
            key=lambda pair: -abs(pair[1]),
        )


def train(
    examples: list[PairwiseExample], *, model: str = "logistic", seed: int = 20260901
) -> TrainedModel:
    """Fits one model. No threshold is chosen here — that is a development-set decision."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    rows = [example.vector() for example in examples]
    labels = [example.label for example in examples]

    if model == "logistic":
        scaler = StandardScaler().fit(rows)
        # `balanced` rather than resampling: the classes are near-even here, and
        # oversampling until a metric improves is how a small set gets overfitted.
        estimator = LogisticRegression(
            max_iter=2000, class_weight="balanced", random_state=seed
        ).fit(scaler.transform(rows), labels)
        return TrainedModel(
            estimator=estimator,
            scaler=scaler,
            threshold=0.5,
            model_class="LogisticRegression",
        )

    estimator = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.1, random_state=seed
    ).fit(rows, labels)
    return TrainedModel(
        estimator=estimator,
        scaler=None,
        threshold=0.5,
        model_class="HistGradientBoostingClassifier",
    )


def select_threshold(
    trained: TrainedModel, development: list[PairwiseExample]
) -> tuple[float, dict]:
    """Applies `THRESHOLD_RULE` to development data only.

    Held-out cases are never consulted. Choosing a threshold against the set you then
    report on is how a benchmark becomes a description of itself.
    """
    scored = [(trained.score(e.features), e) for e in development]
    hard = [
        (score, e)
        for score, e in scored
        if e.label == 0
        and not e.features["service_conflict"]
        and not e.features["issue_conflict"]
    ]
    positives = [score for score, e in scored if e.label == 1]

    best = None
    for step in range(99, 0, -1):
        threshold = step / 100
        false_merges = sum(1 for score, _ in hard if score >= threshold)
        recall = (
            sum(1 for score in positives if score >= threshold) / len(positives)
            if positives
            else 0.0
        )
        if false_merges == 0:
            best = (threshold, recall, false_merges)

    if best is None:
        # No threshold is clean on hard negatives. Take the strictest available and say so.
        threshold, recall, false_merges = 0.99, 0.0, len(hard)
    else:
        threshold, recall, false_merges = best

    return threshold, {
        "rule": THRESHOLD_RULE,
        "selected_threshold": threshold,
        "development_recall_at_threshold": round(recall, 4),
        "development_hard_negative_false_merges": false_merges,
        "development_examples": len(development),
        "development_hard_negatives": len(hard),
    }


def save(trained: TrainedModel, path: Path) -> str:
    """Writes the artifact and returns its hash.

    Joblib rather than pickle-by-hand, and a hash recorded alongside so a decision can be
    traced to the exact artifact that produced it.
    """
    import joblib

    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "estimator": trained.estimator,
            "scaler": trained.scaler,
            "threshold": trained.threshold,
            "model_class": trained.model_class,
            "feature_names": list(trained.feature_names),
            "feature_schema": trained.feature_schema,
            "version": trained.version,
            "metadata": trained.metadata,
        },
        path,
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (path.with_suffix(".json")).write_text(
        json.dumps(
            {
                **trained.metadata,
                "version": trained.version,
                "model_class": trained.model_class,
                "feature_schema": trained.feature_schema,
                "feature_names": list(trained.feature_names),
                "threshold": trained.threshold,
                "artifact_sha256": digest,
                "saved_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        + "\n"
    )
    return digest


def load(path: Path) -> TrainedModel:
    """Loads and validates. A schema mismatch is an error, never a silent reorder."""
    import joblib

    if not path.is_file():
        raise PairwiseModelError(
            f"no pairwise model at {path}. Train one with "
            "`uv run --group pairwise python scripts/train_pairwise.py`."
        )
    try:
        payload = joblib.load(path)
    except Exception as error:  # noqa: BLE001
        raise PairwiseModelError(f"could not load pairwise model: {error}") from error

    if payload.get("feature_schema") != FEATURE_SCHEMA_VERSION:
        raise PairwiseModelError(
            f"model was trained on feature schema {payload.get('feature_schema')!r}, "
            f"this build produces {FEATURE_SCHEMA_VERSION!r}"
        )
    if tuple(payload.get("feature_names", ())) != FEATURE_NAMES:
        raise PairwiseModelError(
            "model feature order does not match this build; refusing to score against a "
            "permuted vector"
        )

    return TrainedModel(
        estimator=payload["estimator"],
        scaler=payload["scaler"],
        threshold=payload["threshold"],
        model_class=payload["model_class"],
        feature_names=tuple(payload["feature_names"]),
        feature_schema=payload["feature_schema"],
        version=payload["version"],
        metadata=payload.get("metadata", {}),
    )
