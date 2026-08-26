"""Provenance records written alongside downloaded and processed data.

Every processed artifact can be traced to the exact upstream revision it came from. The
revision is whatever the source reports — never invented; if a source exposed none, the
field would be absent rather than filled in.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DownloadedFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    filename: str
    sha256: str
    bytes: int


class SourceMetadata(BaseModel):
    """What was downloaded, from where, at which revision."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    revision: str
    license: str
    retrieved_at: datetime
    files: tuple[DownloadedFile, ...]


class ProcessedMetadata(BaseModel):
    """How a processed artifact was produced from a source revision."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    source_revision: str
    license: str
    processed_at: datetime
    source_record_count: int
    processed_record_count: int
    # Present only when a run was deliberately sampled; absent means full corpus.
    sample_limit: int | None = None
    sample_seed: int | None = None
    outputs: tuple[str, ...]
