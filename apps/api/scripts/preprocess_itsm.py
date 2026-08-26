"""Normalize the downloaded ITSM corpus into typed JSONL.

Usage (from apps/api):
    uv run python scripts/preprocess_itsm.py [--limit N] [--seed S]
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.errors import IngestionError  # noqa: E402
from ingestion.io import read_json, write_json, write_jsonl  # noqa: E402
from ingestion.itsm import DATASET_ID, LICENSE, SOURCE_FILE, normalize_rows  # noqa: E402
from ingestion.metadata import ProcessedMetadata, SourceMetadata  # noqa: E402
from ingestion.parquet import read_parquet_rows  # noqa: E402
from ingestion.paths import (  # noqa: E402
    ITSM_PROCESSED_DIR,
    ITSM_RAW_DIR,
    PROCESSED_METADATA_FILE,
    SOURCE_METADATA_FILE,
)
from ingestion.sampling import sample_rows  # noqa: E402

RECORDS_FILE = "records.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ITSM_RAW_DIR)
    parser.add_argument("--out-dir", type=Path, default=ITSM_PROCESSED_DIR)
    parser.add_argument(
        "--limit", type=int, default=None, help="process a deterministic sample"
    )
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    try:
        source = read_json(args.raw_dir / SOURCE_METADATA_FILE, SourceMetadata)
        rows = read_parquet_rows(args.raw_dir / SOURCE_FILE)
        selected = sample_rows(
            rows, key=lambda row: str(row["record_id"]), limit=args.limit, seed=args.seed
        )
        # Everything is normalized and validated before a byte is written.
        records = normalize_rows(selected)
        written = write_jsonl(args.out_dir / RECORDS_FILE, records)
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
            processed_record_count=written,
            sample_limit=args.limit,
            sample_seed=args.seed if args.limit is not None else None,
            outputs=(RECORDS_FILE,),
        ),
    )

    print(f"{DATASET_ID} @ {source.revision}")
    print(f"  source records:    {len(rows)}")
    print(f"  processed records: {written}")
    print(f"  output: {args.out_dir / RECORDS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
