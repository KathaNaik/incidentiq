"""Reproducible downloads from the Hugging Face Hub.

Files are fetched at an explicit revision resolved from the Hub API, never from "latest"
implicitly, so a rerun months from now either produces byte-identical files or reports
that upstream moved.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from ingestion.errors import IngestionError
from ingestion.io import read_json, write_json
from ingestion.metadata import DownloadedFile, SourceMetadata
from ingestion.paths import SOURCE_METADATA_FILE


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_revision(dataset_id: str) -> str:
    try:
        from huggingface_hub import HfApi
    except ImportError as error:  # pragma: no cover - dependency is declared
        raise IngestionError(
            "huggingface-hub is not installed; run `uv sync` in apps/api"
        ) from error

    try:
        info = HfApi().dataset_info(repo_id=dataset_id)
    except Exception as error:
        raise IngestionError(
            f"could not read dataset info for {dataset_id!r} from the Hugging Face Hub. "
            f"Check network access and that the dataset id is correct. Cause: {error}"
        ) from error

    if not info.sha:
        raise IngestionError(f"{dataset_id} did not report a revision")
    return info.sha


def _existing_metadata(destination: Path) -> SourceMetadata | None:
    metadata_path = destination / SOURCE_METADATA_FILE
    if not metadata_path.is_file():
        return None
    return read_json(metadata_path, SourceMetadata)


def download_dataset(
    dataset_id: str,
    filenames: tuple[str, ...],
    destination: Path,
    license_id: str,
    *,
    force: bool = False,
) -> tuple[SourceMetadata, list[str]]:
    """Downloads `filenames` from `dataset_id` into `destination`.

    Reruns are safe: a file already recorded in this directory's metadata at the current
    revision is left alone. A file that exists but was not written by this script is
    never overwritten without `force` — the directory may hold something a person put
    there.

    Returns the metadata written and the list of files actually downloaded.
    """
    revision = _resolve_revision(dataset_id)
    previous = _existing_metadata(destination)
    known = {file.filename: file for file in previous.files} if previous else {}
    revision_matches = previous is not None and previous.revision == revision

    to_download: list[str] = []
    for filename in filenames:
        target = destination / filename
        if not target.is_file():
            to_download.append(filename)
            continue
        if force:
            to_download.append(filename)
            continue

        recorded = known.get(filename)
        if recorded is None:
            raise IngestionError(
                f"{target} already exists but was not recorded by this script. "
                "Move it aside, or rerun with --force to overwrite it."
            )
        if sha256_of(target) != recorded.sha256:
            raise IngestionError(
                f"{target} has changed since it was downloaded. "
                "Rerun with --force to replace it."
            )
        if not revision_matches:
            to_download.append(filename)

    for filename in to_download:
        _fetch(dataset_id, filename, revision, destination)

    files = tuple(
        DownloadedFile(
            filename=filename,
            sha256=sha256_of(destination / filename),
            bytes=(destination / filename).stat().st_size,
        )
        for filename in filenames
    )
    metadata = SourceMetadata(
        dataset_id=dataset_id,
        revision=revision,
        license=license_id,
        retrieved_at=datetime.now(UTC),
        files=files,
    )
    write_json(destination / SOURCE_METADATA_FILE, metadata)
    return metadata, to_download


def _fetch(dataset_id: str, filename: str, revision: str, destination: Path) -> None:
    from huggingface_hub import hf_hub_download

    destination.mkdir(parents=True, exist_ok=True)
    try:
        hf_hub_download(
            repo_id=dataset_id,
            filename=filename,
            repo_type="dataset",
            revision=revision,
            local_dir=destination,
        )
    except Exception as error:
        raise IngestionError(
            f"failed to download {filename} from {dataset_id} at {revision}: {error}"
        ) from error
