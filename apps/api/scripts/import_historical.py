"""Import the historical incident corpus into PostgreSQL.

    uv run --group semantic python scripts/import_historical.py

Safe to re-run. Records are keyed by their stable corpus id, so a second run updates in
place rather than duplicating, and embeddings are reused from the M6 disk cache rather
than recomputed — which is what makes a re-import cheap after the first one.

Sources are the same two the in-memory index used: the authored Northstar records and
the MIT-licensed external corpus. **Polaris is not imported.** It is an external
evaluation dataset under CC BY-SA and folding it into application data would both
misrepresent its provenance and trigger ShareAlike obligations.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.engine import get_engine, session_scope  # noqa: E402
from app.db.models import EMBEDDING_DIMENSIONS, HistoricalIncidentRow  # noqa: E402
from app.db.retrieval_store import historical_row_values  # noqa: E402
from app.embeddings import EmbeddingCache, LocalEmbeddingProvider  # noqa: E402
from app.retrieval import load_corpus  # noqa: E402
from app.retrieval.text import index_text  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--northstar-only",
        action="store_true",
        help="skip the external corpus (useful when it has not been downloaded)",
    )
    args = parser.parse_args()

    settings = get_settings()
    started = time.perf_counter()

    records = load_corpus(
        settings.fixtures_dir,
        settings.itsm_processed_dir,
        include_itsm=not args.northstar_only,
    )
    print(f"corpus: {len(records)} records")

    provider = LocalEmbeddingProvider()
    cache = EmbeddingCache(settings.embeddings_cache_dir, provider)
    if provider.dimensions != EMBEDDING_DIMENSIONS:
        # The column is sized for one model. Writing another model's vectors into it
        # would either fail loudly or, worse, fit and be silently wrong.
        raise SystemExit(
            f"embedding provider produces {provider.dimensions} dimensions but the "
            f"schema stores {EMBEDDING_DIMENSIONS}; a migration is required before "
            "changing embedding model"
        )

    texts = [index_text(record) for record in records]

    embed_started = time.perf_counter()
    cached = [cache.get(value) for value in texts]
    missing = [i for i, vector in enumerate(cached) if vector is None]
    print(f"embeddings: {len(texts) - len(missing)} reused from cache, {len(missing)} to compute")
    if missing:
        computed = provider.embed_many([texts[i] for i in missing])
        for index, vector in zip(missing, computed, strict=True):
            cache.put(texts[index], vector)
            cached[index] = vector
    embed_seconds = time.perf_counter() - embed_started

    rows = [
        historical_row_values(
            record,
            indexed_text=value,
            vector=vector,
            provider_identity=provider.identity,
        )
        for record, value, vector in zip(records, texts, cached, strict=True)
        if vector is not None
    ]
    if len(rows) != len(records):
        raise SystemExit("some records could not be embedded; refusing a partial import")

    write_started = time.perf_counter()
    with session_scope() as session:
        statement = insert(HistoricalIncidentRow).values(rows)
        # Upsert on the primary key: stable corpus ids make a re-import idempotent, and
        # `imported_at` moves so it is clear when a record was last refreshed.
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[HistoricalIncidentRow.id],
                set_={
                    column: statement.excluded[column]
                    for column in rows[0]
                    if column != "id"
                }
                | {"imported_at": text("now()")},
            )
        )
    write_seconds = time.perf_counter() - write_started

    with session_scope() as session:
        total = session.execute(
            text("SELECT count(*) FROM historical_incidents")
        ).scalar_one()
        by_source = session.execute(
            text(
                "SELECT provenance, count(*), count(embedding) "
                "FROM historical_incidents GROUP BY provenance ORDER BY provenance"
            )
        ).all()

    print(f"\nimported in {time.perf_counter() - started:.1f}s")
    print(f"  embedding: {embed_seconds:.1f}s   database write: {write_seconds:.2f}s")
    print(f"  rows: {total}")
    for provenance, count, embedded in by_source:
        print(f"    {provenance}: {count} rows, {embedded} with vectors")
    print(f"  model identity: {provider.identity}")
    get_engine().dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
