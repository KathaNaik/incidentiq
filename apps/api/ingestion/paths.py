"""Default locations for downloaded and processed data.

Computed independently of `app.config` so that ingestion and the runtime API stay
decoupled; both happen to resolve the same repository root.
"""

from pathlib import Path

# apps/api/ingestion/paths.py -> apps/api -> apps -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]

RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

ITSM_RAW_DIR = RAW_DIR / "itsm"
ITSM_PROCESSED_DIR = PROCESSED_DIR / "itsm"
POLARIS_RAW_DIR = RAW_DIR / "polaris"
POLARIS_PROCESSED_DIR = PROCESSED_DIR / "polaris"

SOURCE_METADATA_FILE = "source.json"
PROCESSED_METADATA_FILE = "processed.json"
