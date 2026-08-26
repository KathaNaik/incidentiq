"""Reading source parquet files.

Both datasets publish parquet, so this is the only source format we handle. Rows are
returned as plain dicts: the adapters take dicts, which keeps normalization testable with
hand-authored fixtures instead of binary files.
"""

from pathlib import Path

from ingestion.errors import IngestionError


def read_parquet_rows(path: Path) -> list[dict]:
    if not path.is_file():
        raise IngestionError(
            f"missing source file: {path}. Run the matching download script first."
        )

    try:
        import pyarrow.parquet as pq
    except ImportError as error:  # pragma: no cover - dependency is declared
        raise IngestionError(
            "pyarrow is not installed; run `uv sync` in apps/api"
        ) from error

    try:
        table = pq.read_table(path)
    except Exception as error:
        raise IngestionError(f"could not read parquet file {path}: {error}") from error

    return table.to_pylist()
