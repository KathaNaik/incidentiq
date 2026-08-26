"use client";

import { useEffect, useState } from "react";

import { API_BASE_URL, fetchHealth } from "@/lib/api";

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

  return (
    <div className="rounded border border-neutral-300 p-4 text-sm dark:border-neutral-700">
      <div className="flex items-center gap-2 font-medium">
        <span className={`inline-block h-2 w-2 rounded-full ${indicator}`} />
        <span>
          {status.kind === "checking" && "Checking API…"}
          {status.kind === "reachable" && `API reachable — ${status.service}`}
          {status.kind === "unreachable" && "API unreachable"}
        </span>
      </div>
      <p className="mt-2 text-neutral-600 dark:text-neutral-400">
        <code>GET {API_BASE_URL}/health</code>
        {status.kind === "unreachable" && ` — ${status.reason}`}
      </p>
      {status.kind === "unreachable" && (
        <p className="mt-1 text-neutral-600 dark:text-neutral-400">
          Start the backend with <code>uv run uvicorn app.main:app --reload --port 8001</code>{" "}
          in <code>apps/api</code>.
        </p>
      )}
    </div>
  );
}
