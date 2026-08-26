"""Deterministic sampling for local experimentation.

Sampling happens once, on source rows, before any feature/label split. Sampling the two
views independently would silently break their alignment — the failure mode this design
removes rather than tests for.
"""

import random
from collections.abc import Callable

from ingestion.errors import IngestionError


def sample_rows(
    rows: list[dict], *, key: Callable[[dict], str], limit: int | None, seed: int
) -> list[dict]:
    """Returns `limit` rows chosen deterministically from `rows`.

    The choice depends only on the record ids and the seed, so it is stable across runs
    and independent of the order the source happened to arrive in. Source order is then
    preserved in the output.
    """
    if limit is None:
        return rows
    if limit <= 0:
        raise IngestionError(f"--limit must be positive, got {limit}")
    if limit >= len(rows):
        return rows

    identifiers = sorted(key(row) for row in rows)
    chosen = set(random.Random(seed).sample(identifiers, limit))
    return [row for row in rows if key(row) in chosen]
