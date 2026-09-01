"use client";

import { useEffect, useState } from "react";

import { API_BASE_URL, fetchHealth } from "@/lib/api";

// The backend is a scale-to-zero service in production: nobody starts it, and telling a
// visitor to run uvicorn would be advice they cannot act on and that misdescribes the
// deployment. The instruction belongs only where it is true.
const IS_LOCAL = process.env.NODE_ENV !== "production";

type Status =
  | { kind: "checking" }
  | { kind: "reachable"; service: string }
  | { kind: "unreachable"; reason: string };

/**
 * Calls the real backend from the browser and reports what happened. This is the only
 * frontend/backend connection in the milestone — it must never be stubbed, or it stops
 * telling us anything.
 */
export function ApiStatus() {
  const [status, setStatus] = useState<Status>({ kind: "checking" });

  useEffect(() => {
    const controller = new AbortController();

    fetchHealth(controller.signal)
      .then((health) => setStatus({ kind: "reachable", service: health.service }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setStatus({
          kind: "unreachable",
          reason: error instanceof Error ? error.message : "Unknown error",
        });
      });

    return () => controller.abort();
  }, []);

  const indicator = {
    checking: "bg-neutral-400",
    reachable: "bg-green-500",
    unreachable: "bg-red-500",
  }[status.kind];

  // Healthy is the overwhelmingly common case and carries no decision, so it gets one
  // line. Failure is the case worth space, and only then does this expand into an
  // explanation somebody can act on.
  if (status.kind !== "unreachable") {
    return (
      <p className="flex items-center gap-2 text-xs text-neutral-500">
        <span className={`inline-block h-1.5 w-1.5 rounded-full ${indicator}`} />
        {status.kind === "checking" ? "Checking API…" : `API healthy · ${status.service}`}
      </p>
    );
  }

  return (
    <div
      className="rounded border border-red-300 p-4 text-sm dark:border-red-900"
      role="alert"
    >
      <div className="flex items-center gap-2 font-medium">
        <span className={`inline-block h-2 w-2 rounded-full ${indicator}`} />
        <span>API unreachable</span>
      </div>
      <p className="mt-2 text-neutral-600 dark:text-neutral-400">
        <code>GET {API_BASE_URL}/health</code> — {status.reason}
      </p>
      {IS_LOCAL && (
        <p className="mt-1 text-neutral-600 dark:text-neutral-400">
          Start the backend with{" "}
          <code>uv run uvicorn app.main:app --reload --port 8001</code> in{" "}
          <code>apps/api</code>, or run <code>vercel dev</code> from the repository root to
          start both services together.
        </p>
      )}
    </div>
  );
}
