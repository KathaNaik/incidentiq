"""JSONL and JSON helpers.

Writes are atomic: records are validated in full and written to a temporary file that
replaces the target only on success, so an interrupted or failing run never leaves a
half-written corpus that looks complete.
"""

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ingestion.errors import IngestionError

ModelT = TypeVar("ModelT", bound=BaseModel)


def write_jsonl(path: Path, records: Iterable[BaseModel]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    count = 0
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(record.model_dump_json())
                handle.write("\n")
                count += 1
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return count


def read_jsonl(path: Path, model: type[ModelT]) -> Iterator[ModelT]:
    """Reads a processed artifact back as typed records."""
    if not path.is_file():
        raise IngestionError(f"missing processed file: {path}")

    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield model.model_validate_json(line)
            except ValidationError as error:
                raise IngestionError(f"{path.name} line {number}: {error}") from error


def write_json(path: Path, payload: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload.model_dump_json(indent=2) + "\n", encoding="utf-8")


def read_json(path: Path, model: type[ModelT]) -> ModelT:
    if not path.is_file():
        raise IngestionError(f"missing metadata file: {path}")
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        raise IngestionError(f"invalid metadata in {path.name}: {error}") from error


def load_json_rows(path: Path) -> list[dict]:
    """Reads a JSON array of row dicts — the shape the preprocessors normalize."""
    if not path.is_file():
        raise IngestionError(f"missing source file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise IngestionError(f"{path.name} must contain a JSON array of records")
    return payload
