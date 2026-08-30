"use client";

import { useState } from "react";

import { resetDemoState } from "@/lib/api";

/**
 * Clears in-memory action state so the walkthrough can be run again.
 *
 * Deliberately visible and deliberately labelled. Action state lives in process memory,
 * so once the hero rollback has been approved and executed the next run opens on a
 * finished action; the alternative to this button is restarting the API mid-demo.
 *
 * It is not administration tooling: it clears actions and audit events and nothing else,
 * and the API refuses it outside development regardless of what this renders.
 */
export function DemoReset() {
  const [state, setState] = useState<
    { kind: "idle" } | { kind: "busy" } | { kind: "done"; message: string } | { kind: "error"; message: string }
  >({ kind: "idle" });

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
          Clears in-memory actions, approvals and audit events. Fixtures, evaluation
          artifacts and recorded runs are files on disk and are not touched.
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
