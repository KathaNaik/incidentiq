"""Download the Polaris support ticket corpus (CC BY-SA 4.0).

Evaluation data only. Nothing downloaded here may be committed — `data/raw/` is
gitignored, and redistributing adapted copies would carry ShareAlike obligations.

Usage (from apps/api):
    uv run python scripts/download_polaris.py [--force]
"""

import argparse
import sys
from pathlib import Path

# Runnable both as `python scripts/download_polaris.py` and `python -m scripts.download_polaris`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.download import download_dataset  # noqa: E402
from ingestion.errors import IngestionError  # noqa: E402
from ingestion.paths import POLARIS_RAW_DIR  # noqa: E402
from ingestion.polaris.features import DATASET_ID, LICENSE, SOURCE_FILE  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=POLARIS_RAW_DIR)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing files in the destination",
    )
    args = parser.parse_args()

    try:
        metadata, downloaded = download_dataset(
            DATASET_ID, (SOURCE_FILE,), args.dest, LICENSE, force=args.force
        )
    except IngestionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"{DATASET_ID} @ {metadata.revision}")
    print(f"  destination: {args.dest}")
    for file in metadata.files:
        state = "downloaded" if file.filename in downloaded else "already present"
        print(f"  {file.filename}: {file.bytes} bytes ({state})")
    print(f"  license: {metadata.license} — evaluation only, never committed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
