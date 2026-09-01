"use client";

import { useState } from "react";

import { resetDemoState } from "@/lib/api";

/**
 * Clears workflow state so the walkthrough can be run again.
 *
 * Renders only in local development. The API has always refused this outside
 * development, so in production it was a visible button that could only ever return 403 —
 * an offer the deployment cannot honour, which is worse than no button.
 *
 * It is not administration tooling: it clears actions, approvals, executions and audit
 * events, and nothing else. Reports, incidents, correlation state and recorded
 * investigation runs survive it.
 */
const IS_LOCAL = process.env.NODE_ENV !== "production";

export function DemoReset() {
  const [state, setState] = useState<
    { kind: "idle" } | { kind: "busy" } | { kind: "done"; message: string } | { kind: "error"; message: string }
  >({ kind: "idle" });

  // After the hooks, never before: bailing out early would call a different number of
  // hooks between renders.
  if (!IS_LOCAL) return null;

  async function reset() {
    setState({ kind: "busy" });
    try {
      const result = await resetDemoState();
      setState({
        kind: "done",
        message: `Cleared ${result.cleared_actions} action(s) and ${result.cleared_audit_events} audit event(s). Reload to see the queue reset.`,
      });
    } catch (caught) {
      setState({
        kind: "error",
        message: caught instanceof Error ? caught.message : "Reset failed",
      });
    }
  }

  return (
    <section className="rounded border border-dashed border-neutral-300 p-4 dark:border-neutral-700">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs font-medium tracking-wide text-neutral-500 uppercase">
          Demo control
        </span>
        <button
          type="button"
          onClick={reset}
          disabled={state.kind === "busy"}
          className="rounded border border-neutral-400 px-3 py-1 text-sm disabled:opacity-50 dark:border-neutral-600"
        >
          {state.kind === "busy" ? "Resetting…" : "Reset workflow state"}
        </button>
        <span className="text-xs text-neutral-500">
          Clears actions, approvals, executions and audit events from the database.
          Reports, incidents, correlation state and recorded investigation runs are not
          touched.
        </span>
      </div>
      {state.kind === "done" && (
        <p className="mt-2 text-sm text-neutral-700 dark:text-neutral-300">
          {state.message}
        </p>
      )}
      {state.kind === "error" && (
        <p className="mt-2 text-sm text-red-700 dark:text-red-400">{state.message}</p>
      )}
    </section>
  );
}
