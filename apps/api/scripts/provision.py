"""Prepare a database for IncidentIQ. Run once per environment, safe to re-run.

    DATABASE_URL=<target> uv run --group semantic python scripts/provision.py

Three steps in the order they depend on each other: migrate the schema (which also
creates the pgvector extension), seed the authored Northstar tickets, then import the
historical corpus and its vectors.

**This is deliberately not run on API startup.** Vercel scales the backend horizontally,
so a migration on boot would have every instance racing to alter the same schema, and a
failed race is a half-migrated production database. Migrations are an operator action
with a person watching, which is why they live here.

Against a managed provider that offers both a pooled and a direct connection string, use
the **direct** one here. Schema changes and long transactions do not belong on a
transaction pooler; the pooled URL is for the running application.

Nothing here fabricates operator activity. No reviews, approvals, executions or
investigation runs are seeded — a deployed demo starts from coherent operational input,
not from invented history that implies work somebody did not do.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _run(label: str, command: list[str]) -> float:
    print(f"\n=== {label} ===", flush=True)
    started = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT)
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise SystemExit(f"{label} failed with exit code {result.returncode}")
    print(f"  {label}: {elapsed:.1f}s", flush=True)
    return elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-history",
        action="store_true",
        help="skip the historical corpus import (it needs the semantic group)",
    )
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print(
            "error: DATABASE_URL is not set. Point it at the database you intend to "
            "provision — this writes schema and data.",
            file=sys.stderr,
        )
        return 1

    # Enough to confirm the operator is aimed at the right database, without printing a
    # password into a terminal or a CI log.
    host = url.split("@")[-1].split("/")[0] if "@" in url else "(local)"
    database = url.rstrip("/").split("/")[-1].split("?")[0]
    print(f"provisioning {database} at {host}")

    timings = {
        "migrate": _run("migrate", ["uv", "run", "alembic", "upgrade", "head"]),
        "seed": _run("seed", ["uv", "run", "python", "scripts/seed_tickets.py"]),
    }

    if not args.skip_history:
        timings["history"] = _run(
            "import history",
            [
                "uv",
                "run",
                "--group",
                "semantic",
                "python",
                "scripts/import_historical.py",
            ],
        )

    print("\n=== done ===")
    for step, seconds in timings.items():
        print(f"  {step:<16} {seconds:6.1f}s")
    print(
        "\nEvery step is idempotent. Re-running updates in place rather than "
        "duplicating, so this is safe to repeat after a redeploy."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
