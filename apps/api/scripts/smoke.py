"""Smoke-test a deployed IncidentIQ.

    uv run python scripts/smoke.py --base-url https://<deployment>

Read-only by default. It checks that the service is up, that its schema matches the
build, that the durable state a reviewer will look at is actually there, and that the
production guards are on. It does **not** submit tickets, approve actions or run
investigations, because the default behaviour of a smoke test should never be to spend
money or mutate somebody's demo.

    --mutate    also submits one uniquely-prefixed ticket and resolves the review it
                creates. Still never approves, executes, or calls the model.

Exit code is 0 only if every check passed.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

TIMEOUT = 60


class Result:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []
        self.timings: dict[str, float] = {}

    def check(self, name: str, ok: bool, detail: str = "", seconds: float | None = None) -> bool:
        if seconds is not None:
            self.timings[name] = seconds
        mark = "PASS" if ok else "FAIL"
        timing = f"  {seconds * 1000:7.0f}ms" if seconds is not None else ""
        print(f"  [{mark}] {name}{timing}{'  ' + detail if detail else ''}")
        if ok:
            self.passed += 1
        else:
            self.failed.append(f"{name}: {detail}" if detail else name)
        return ok


def request(url: str, method: str = "GET", body: dict | None = None):
    """Returns (status, parsed_json_or_text, seconds)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            elapsed = time.perf_counter() - started
            raw = response.read().decode()
            try:
                return response.status, json.loads(raw), elapsed
            except json.JSONDecodeError:
                return response.status, raw, elapsed
    except urllib.error.HTTPError as error:
        elapsed = time.perf_counter() - started
        raw = error.read().decode()
        try:
            return error.code, json.loads(raw), elapsed
        except json.JSONDecodeError:
            return error.code, raw, elapsed
    except Exception as error:  # noqa: BLE001 - reported, not raised
        return 0, str(error), time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="deployment origin")
    parser.add_argument(
        "--mutate",
        action="store_true",
        help="also submit one prefixed ticket and resolve its review",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    api = f"{base}/api"
    r = Result()

    print(f"\nIncidentIQ smoke test — {base}\n")

    print("service")
    status, body, seconds = request(f"{api}/health")
    r.check("health", status == 200 and body.get("status") == "ok", "", seconds)
    r.check(
        "environment is production",
        isinstance(body, dict) and body.get("environment") == "production",
        f"got {body.get('environment') if isinstance(body, dict) else body!r}",
    )

    status, body, seconds = request(f"{api}/ready")
    ready = isinstance(body, dict) and body.get("ready") is True
    r.check("ready", status == 200 and ready, "", seconds)
    if isinstance(body, dict):
        r.check(
            "schema matches the build",
            body.get("schema_current") is True,
            f"db={body.get('schema_revision')} build={body.get('expected_revision')}",
        )

    print("\ndurable state")
    status, body, seconds = request(f"{api}/intake/candidates")
    r.check(
        "candidates present",
        status == 200 and isinstance(body, list) and len(body) > 0,
        f"{len(body) if isinstance(body, list) else 0} candidates",
        seconds,
    )

    status, body, seconds = request(f"{api}/intake/tickets")
    tickets = len(body) if isinstance(body, list) else 0
    r.check("tickets present", status == 200 and tickets > 0, f"{tickets} tickets", seconds)

    status, body, seconds = request(f"{api}/correlation-reviews?pending_only=false")
    r.check("review queue reachable", status == 200 and isinstance(body, list), "", seconds)

    # Historical retrieval is the one read that exercises pgvector *and* the baked
    # embedding model, so it is the check that proves a cold instance is complete.
    status, body, seconds = request(
        f"{api}/retrieval/historical-incidents?k=3",
        method="POST",
        body={"text": "users cannot sign in through the identity provider"},
    )
    hits = body.get("hits", []) if isinstance(body, dict) else []
    corpus = body.get("corpus_size", 0) if isinstance(body, dict) else 0
    r.check(
        "pgvector historical retrieval",
        status == 200 and len(hits) > 0,
        f"{len(hits)} hits over {corpus} records",
        seconds,
    )

    print("\nevaluation artifacts")
    for name, path in [
        ("triage", "/evals/triage"),
        ("correlation", "/evals/correlation"),
        ("policy", "/evals/policy"),
    ]:
        status, body, seconds = request(f"{api}{path}")
        r.check(f"evals {name}", status == 200, "", seconds)

    print("\nfrontend")
    for name, path in [
        ("dashboard", "/"),
        ("tickets", "/tickets"),
        ("reviews", "/reviews"),
        ("incidents", "/incidents"),
        ("evals", "/evals"),
    ]:
        status, _, seconds = request(f"{base}{path}")
        r.check(f"page {name}", status == 200, "", seconds)

    print("\nproduction guards")
    status, body, _ = request(f"{api}/demo/reset", method="POST")
    r.check("demo reset refused", status == 403, f"got {status}")

    status, body, _ = request(
        f"{api}/tickets", method="POST", body={"external_id": "", "title": ""}
    )
    r.check("invalid payload rejected cleanly", 400 <= status < 500, f"got {status}")

    status, body, _ = request(f"{api}/tickets", method="POST", body={"nonsense": True})
    leaked = isinstance(body, str) and ("Traceback" in body or "postgresql://" in body)
    r.check("no stack trace or credential in error", not leaked, f"got {status}")

    if args.mutate:
        print("\nmutation (explicitly requested)")
        marker = f"SMOKE-{uuid.uuid4().hex[:8].upper()}"
        status, body, seconds = request(
            f"{api}/tickets",
            method="POST",
            body={
                "external_id": marker,
                "title": "Smoke test: users report the console never finishes loading",
                "description": (
                    "Automated smoke test ticket. Everyone gets past sign-in and then "
                    "the workspace never finishes opening."
                ),
                "reported_service_id": "svc-auth",
            },
        )
        created = status in (200, 201) and isinstance(body, dict)
        r.check("ticket intake", created, marker, seconds)
        if created:
            outcome = body.get("correlation", {}).get("outcome")
            version = body.get("correlation", {}).get("correlation_version")
            r.check("triage ran", body.get("triage", {}).get("service_id") is not None)
            r.check(
                "correlation v2 recorded",
                version == "deterministic-correlation-v2",
                f"got {version}",
            )
            print(f"         correlation outcome: {outcome}")

        status, reviews, seconds = request(f"{api}/correlation-reviews")
        mine = (
            [rv for rv in reviews if rv["ticket_snapshot"]["external_id"] == marker]
            if isinstance(reviews, list)
            else []
        )
        if mine:
            status, body, seconds = request(
                f"{api}/correlation-reviews/{mine[0]['id']}/reject",
                method="POST",
                body={"reason": "insufficient_evidence", "note": "Automated smoke test."},
            )
            r.check("review reject", status == 200, "", seconds)
        else:
            print("         no review created for the smoke ticket (not a failure)")

    print(f"\n{r.passed} passed, {len(r.failed)} failed")
    for failure in r.failed:
        print(f"  FAILED  {failure}")
    if r.timings:
        print("\nrepresentative timings (single samples, not a distribution)")
        for name, seconds in sorted(r.timings.items(), key=lambda kv: -kv[1])[:8]:
            print(f"  {name:<34} {seconds * 1000:7.0f}ms")
    return 1 if r.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
