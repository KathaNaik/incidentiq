"""Split the downloaded Polaris corpus into aligned feature and label artifacts.

Features and labels are written to separate files on purpose: a consumer must choose to
open the label file, and nothing that reads features can stumble into ground truth.

Usage (from apps/api):
    uv run python scripts/preprocess_polaris.py [--limit N] [--seed S]
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.errors import IngestionError  # noqa: E402
from ingestion.io import read_json, write_json, write_jsonl  # noqa: E402
from ingestion.metadata import ProcessedMetadata, SourceMetadata  # noqa: E402
from ingestion.parquet import read_parquet_rows  # noqa: E402
from ingestion.paths import (  # noqa: E402
    POLARIS_PROCESSED_DIR,
    POLARIS_RAW_DIR,
    PROCESSED_METADATA_FILE,
    SOURCE_METADATA_FILE,
)
from ingestion.polaris.features import (  # noqa: E402
    DATASET_ID,
    JOIN_KEY,
    LICENSE,
    SOURCE_FILE,
)
from ingestion.polaris.normalize import split_rows  # noqa: E402
from ingestion.sampling import sample_rows  # noqa: E402

FEATURES_FILE = "features.jsonl"
LABELS_FILE = "labels.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=POLARIS_RAW_DIR)
    parser.add_argument("--out-dir", type=Path, default=POLARIS_PROCESSED_DIR)
    parser.add_argument(
        "--limit", type=int, default=None, help="process a deterministic sample"
    )
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    try:
        source = read_json(args.raw_dir / SOURCE_METADATA_FILE, SourceMetadata)
        rows = read_parquet_rows(args.raw_dir / SOURCE_FILE)
        # Sampled once, before the split, so features and labels can never diverge.
        selected = sample_rows(
            rows, key=lambda row: str(row[JOIN_KEY]), limit=args.limit, seed=args.seed
        )
        features, labels = split_rows(selected)
        feature_count = write_jsonl(args.out_dir / FEATURES_FILE, features)
        label_count = write_jsonl(args.out_dir / LABELS_FILE, labels)
    except IngestionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyError as error:
        print(f"error: source row is missing {error}", file=sys.stderr)
        return 1

    write_json(
        args.out_dir / PROCESSED_METADATA_FILE,
        ProcessedMetadata(
            dataset_id=DATASET_ID,
            source_revision=source.revision,
            license=LICENSE,
            processed_at=datetime.now(UTC),
            source_record_count=len(rows),
            processed_record_count=feature_count,
            sample_limit=args.limit,
            sample_seed=args.seed if args.limit is not None else None,
            outputs=(FEATURES_FILE, LABELS_FILE),
        ),
    )

    labelled = sum(1 for label in labels if label.event_id is not None)
    print(f"{DATASET_ID} @ {source.revision}")
    print(f"  source records:    {len(rows)}")
    print(f"  feature records:   {feature_count}")
    print(f"  label records:     {label_count}")
    print(f"  tickets tied to a service event: {labelled}")
    print(f"  outputs: {args.out_dir / FEATURES_FILE}, {args.out_dir / LABELS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
