"""Expanded authored-world regression for Northstar world v2.

    DATABASE_URL=<target> uv run python scripts/world_v2_check.py

Runs the authored world through the current runtime **once** and records what happened,
scored against the ground truth frozen in `docs/NORTHSTAR_WORLD_V2.md`.

This is **not** a benchmark and not a replacement for any historical eval. It is a richer
authored regression over a world the same author wrote, which makes it useful for spotting
change and useless as evidence of generalisation. Nothing is tuned in response to it — the
whole point of freezing the design first was that this number is allowed to be bad.

Historical artifacts under `data/evals/` are not touched. Output goes to a separately named
file so it can never be mistaken for one.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.correlation import correlate  # noqa: E402
from app.correlation.models import CorrelationTicket  # noqa: E402
from app.db.engine import get_engine, session_scope  # noqa: E402
from app.db.models import CandidateIncidentRow, TicketRow  # noqa: E402
from app.fixtures import load_dataset  # noqa: E402
from sqlalchemy import select  # noqa: E402

ARTIFACT = "northstar-world-v2-runtime-check"

#: Boundary-case truth, transcribed from the frozen design. The justification stays in the
#: document; only the label is needed here.
BOUNDARY_TRUTH = {
    "TKT-4401": ("SAME", "INC-1044"),
    "TKT-4402": ("DIFFERENT", "INC-1044"),
    "TKT-4403": ("SAME", "INC-1045"),
    "TKT-4404": ("AMBIGUOUS", None),
    "TKT-4405": ("SAME", "INC-1047"),
    "TKT-4406": ("DIFFERENT", "INC-1047"),
    "TKT-4407": ("SAME", "INC-1048"),
    "TKT-4408": ("SAME", "INC-1049"),
    "TKT-4409": ("DIFFERENT", "INC-1050"),
    "TKT-4410": ("SAME", "INC-1051"),
}

ISOLATED = [f"TKT-43{n:02d}" for n in range(1, 15)]


def main() -> int:
    settings = get_settings()
    dataset = load_dataset(settings.fixtures_dir)

    declared: dict[str, set[str]] = defaultdict(set)
    for link in dataset.incident_tickets:
        declared[link.incident_id].add(link.ticket_id)

    with session_scope() as session:
        rows = session.scalars(
            select(TicketRow).order_by(TicketRow.created_at, TicketRow.id)
        ).all()
        placed = {row.id: row.candidate_id for row in rows}
        candidates = {
            row.id: row for row in session.scalars(select(CandidateIncidentRow)).all()
        }
        members: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            if row.candidate_id:
                members[row.candidate_id].add(row.id)

    # Recompute the grouping the batch engine forms over the whole authored world. This is
    # what the seed acted on, so it explains the persisted candidates.
    window = [
        CorrelationTicket(
            id=row.id,
            title=row.title,
            description=row.description,
            created_at=row.created_at,
            service_id=row.service_id,
            reported_by=row.reported_by,
        )
        for row in rows
    ]
    grouped = correlate(window)

    # --- per-incident recall ------------------------------------------------------------
    per_incident = []
    for incident_id, truth in sorted(declared.items()):
        # The candidate holding the most members of this incident, if any.
        by_candidate: dict[str, int] = defaultdict(int)
        for ticket_id in truth:
            candidate = placed.get(ticket_id)
            if candidate:
                by_candidate[candidate] += 1
        best, recovered = (
            max(by_candidate.items(), key=lambda kv: kv[1]) if by_candidate else (None, 0)
        )
        contamination = (
            sorted(members[best] - truth) if best else []
        )
        per_incident.append(
            {
                "incident": incident_id,
                "declared_members": len(truth),
                "grouped_into_one_candidate": recovered,
                "candidate": best,
                "unrelated_reports_in_that_candidate": contamination,
            }
        )

    # --- isolated traffic ---------------------------------------------------------------
    false_attachments = [
        {"ticket": ticket_id, "attached_to": placed[ticket_id]}
        for ticket_id in ISOLATED
        if placed.get(ticket_id)
    ]

    # --- boundary cases -----------------------------------------------------------------
    boundary = []
    for ticket_id, (truth, near) in BOUNDARY_TRUTH.items():
        candidate = placed.get(ticket_id)
        boundary.append(
            {
                "ticket": ticket_id,
                "frozen_truth": truth,
                "intended_incident": near,
                "runtime_outcome": "attached" if candidate else "not attached",
                "attached_to": candidate,
            }
        )

    report = {
        "artifact": ARTIFACT,
        "kind": "expanded authored-world regression",
        "not_a_benchmark": (
            "Authored and scored by the same author over a world designed before it was "
            "run. Useful for detecting change; not evidence of generalisation, and not a "
            "replacement for any historical eval."
        ),
        "world": {
            "services": len(dataset.services),
            "tickets": len(rows),
            "declared_incidents": len(declared),
            "declared_incident_members": sum(len(v) for v in declared.values()),
            "isolated_reports": len(ISOLATED),
            "boundary_reports": len(BOUNDARY_TRUTH),
        },
        "grouping": {
            "candidates_persisted": len(candidates),
            "candidates_from_batch_engine": len(grouped.candidates),
            "tickets_in_a_candidate": sum(1 for v in placed.values() if v),
            "tickets_standalone": sum(1 for v in placed.values() if not v),
        },
        "per_incident": per_incident,
        "false_attachments_of_isolated_traffic": false_attachments,
        "boundary_cases": boundary,
    }

    directory = Path(settings.correlation_evals_dir).parent / "world"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{ARTIFACT}.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    # --- console summary ----------------------------------------------------------------
    print(f"\n{ARTIFACT} — expanded authored-world regression\n")
    w = report["world"]
    print(f"  world: {w['services']} services · {w['tickets']} tickets · "
          f"{w['declared_incidents']} declared incidents")
    g = report["grouping"]
    print(f"  grouping: {g['candidates_persisted']} candidates · "
          f"{g['tickets_in_a_candidate']} tickets grouped · "
          f"{g['tickets_standalone']} standalone\n")

    print("  per declared incident (members grouped into one candidate):")
    for row in per_incident:
        mark = "  " if row["grouped_into_one_candidate"] >= 2 else "  "
        extra = (
            f"  +{len(row['unrelated_reports_in_that_candidate'])} unrelated"
            if row["unrelated_reports_in_that_candidate"]
            else ""
        )
        print(
            f"  {mark}{row['incident']}: "
            f"{row['grouped_into_one_candidate']}/{row['declared_members']}{extra}"
        )

    print(f"\n  isolated traffic falsely attached: {len(false_attachments)}/{len(ISOLATED)}")
    for item in false_attachments:
        print(f"    {item['ticket']} -> {item['attached_to']}")

    print("\n  boundary cases (frozen truth vs runtime):")
    for row in boundary:
        print(
            f"    {row['ticket']}  {row['frozen_truth']:<9} -> {row['runtime_outcome']}"
            + (f" ({row['attached_to']})" if row["attached_to"] else "")
        )

    print(f"\n  written: {directory / (ARTIFACT + '.json')}")
    print(
        "\n  Labelled an expanded authored-world regression. Not a benchmark, and not "
        "evidence that evaluation became more reliable."
    )
    get_engine().dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
