"use client";

import { useState } from "react";

import { Badge } from "@/components/badge";
import { probePolicy, type InvestigationResult, type PolicyProbeResult } from "@/lib/api";

/**
 * The rejection path, on demand.
 *
 * Policy is most interesting when it says no, and on these fixtures the model correctly
 * recommends a rollback — so the refusal never appears on its own. This asks policy what
 * it *would* decide about an action nobody recommended.
 *
 * Labelled hypothetical everywhere, and it is: no model produced this, no action is
 * created, nothing can be approved or executed from here. Dressing a fabricated
 * recommendation up as a real one would undo the point of the whole page.
 */
export function PolicyProbe({
  investigation,
  serviceId,
}: {
  investigation: InvestigationResult;
  serviceId: string | null;
}) {
  const [result, setResult] = useState<PolicyProbeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function probe() {
    setBusy(true);
    setError(null);
    try {
      setResult(await probePolicy(investigation, "restart_service", serviceId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Probe failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded border border-dashed border-neutral-300 p-4 dark:border-neutral-700">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs font-medium tracking-wide text-neutral-500 uppercase">
          Policy demonstration
        </span>
        <button
          type="button"
          onClick={probe}
          disabled={busy}
          className="rounded border border-neutral-400 px-3 py-1 text-sm disabled:opacity-50 dark:border-neutral-600"
        >
          {busy ? "Asking policy…" : "What if a restart had been recommended?"}
        </button>
      </div>
      <p className="mt-2 text-xs text-neutral-500">
        Asks the deterministic policy about an action <strong>no model recommended</strong>.
        Creates nothing and cannot be approved or executed.
      </p>

      {error && (
        <p className="mt-2 text-sm text-red-700 dark:text-red-400">{error}</p>
      )}

      {result && (
        <div className="mt-3 rounded border border-neutral-400 p-3 dark:border-neutral-600">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-medium">
              {result.action_type.replace(/_/g, " ")}
            </h4>
            <Badge tone={result.policy.eligible ? "info" : "danger"}>
              {result.policy.eligible ? "Would be eligible" : "Would be blocked"}
            </Badge>
            <Badge>hypothetical</Badge>
          </div>
          <ul className="mt-2 space-y-1 text-sm">
            {result.policy.reasons.map((reason) => (
              <li key={reason.check}>
                <span
                  className={
                    reason.passed
                      ? "text-green-700 dark:text-green-500"
                      : "text-amber-700 dark:text-amber-500"
                  }
                >
                  {reason.passed ? "✓" : "✗"}
                </span>{" "}
                <span className="font-mono text-xs text-neutral-500">
                  {reason.check}
                </span>{" "}
                {reason.detail}
              </li>
            ))}
          </ul>
          {!result.policy.eligible && (
            <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
              No approve button appears for an action in this state. The service really is
              degraded — but a restart reloads the same configuration and re-reads the
              same credentials, so it would cost an outage and fix nothing.
            </p>
          )}
          <p className="mt-2 text-xs text-neutral-500">{result.note}</p>
        </div>
      )}
    </div>
  );
}
