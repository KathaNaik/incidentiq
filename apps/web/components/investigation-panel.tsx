"use client";

import { useState } from "react";

import { Badge } from "@/components/badge";
import { Investigation } from "@/components/investigation";
import {
  fetchInvestigationRun,
  runInvestigation,
  type InvestigationRunDetail,
  type InvestigationRunSummary,
  type LatestInvestigation,
} from "@/lib/api";
import { formatTimestamp } from "@/lib/format";

/**
 * The investigation section, reading stored runs.
 *
 * Before M13 this rendered by calling the model: opening an incident cost eleven seconds
 * and a set of tokens, and a reload could return a different answer than the one the
 * operator had just been reading. Now the server hands over what was stored, and a model
 * call happens only when someone asks for one.
 *
 * Re-running never replaces anything. It creates a new run and the old ones stay
 * inspectable, which is what makes "what did the model see when it recommended this"
 * answerable after the fact.
 */
export function InvestigationPanel({
  incidentId,
  serviceId,
  initial,
  history,
}: {
  incidentId: string;
  serviceId: string | null;
  initial: LatestInvestigation | null;
  history: InvestigationRunSummary[];
}) {
  const [current, setCurrent] = useState<InvestigationRunDetail | null>(
    initial?.current ?? null,
  );
  const [runs, setRuns] = useState<InvestigationRunSummary[]>(history);
  const [viewing, setViewing] = useState<InvestigationRunDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const run = await runInvestigation(incidentId);
      if (run.status === "succeeded") {
        setCurrent(run);
        setViewing(null);
      }
      setRuns([run, ...runs.filter((entry) => entry.id !== run.id)]);
      if (run.status === "failed") {
        setError(
          `Investigation ${run.id} failed (${run.failure_type}). The previous result, if any, is unchanged.`,
        );
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Investigation failed");
    } finally {
      setBusy(false);
    }
  }

  async function inspect(runId: string) {
    setError(null);
    try {
      setViewing(await fetchInvestigationRun(runId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load that run");
    }
  }

  const shown = viewing ?? current;

  if (busy && !shown) {
    return <RunningNotice />;
  }

  if (!shown) {
    return (
      <div className="space-y-3">
        <div className="rounded border border-dashed border-neutral-300 p-6 dark:border-neutral-700">
          <p className="text-sm font-medium">No investigation has been run</p>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Everything above is deterministic and already final. Investigating calls a
            language model once, takes several seconds, and stores the result — opening
            this page does not do it on your behalf.
          </p>
          <button
            type="button"
            onClick={start}
            disabled={busy}
            className="mt-3 rounded border border-neutral-400 px-3 py-1 text-sm disabled:opacity-50 dark:border-neutral-600"
          >
            {busy ? "Investigating…" : "Run AI investigation"}
          </button>
        </div>
        {error && <ErrorNote message={error} />}
      </div>
    );
  }

  const isHistorical = viewing !== null && viewing.id !== current?.id;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
        <Badge tone={isHistorical ? "warn" : "info"}>
          {isHistorical ? "historical run" : "current"}
        </Badge>
        <span>Investigated {formatTimestamp(shown.completed_at ?? shown.created_at)}</span>
        <span>·</span>
        <span>{shown.investigator_version}</span>
        <span>·</span>
        <span>{shown.prompt_version}</span>
        <span>·</span>
        <span>{shown.model}</span>
        <span>·</span>
        <code className="text-xs">{shown.id}</code>
        {shown.latency_ms !== null && <span>· {shown.latency_ms} ms</span>}
      </div>

      {isHistorical && (
        <p className="rounded border border-amber-300 p-3 text-sm dark:border-amber-900">
          Showing an earlier run and the evidence <em>it</em> saw, not current evidence.{" "}
          <button
            type="button"
            onClick={() => setViewing(null)}
            className="underline underline-offset-2"
          >
            Back to the current investigation
          </button>
        </p>
      )}

      {busy && <RunningNotice />}

      {shown.result && (
        <Investigation
          result={shown.result}
          serviceId={serviceId}
          investigationRunId={shown.id}
          readOnly={isHistorical}
        />
      )}

      {error && <ErrorNote message={error} />}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={start}
          disabled={busy}
          className="rounded border border-neutral-400 px-3 py-1 text-sm disabled:opacity-50 dark:border-neutral-600"
        >
          {busy ? "Investigating…" : "Re-run investigation"}
        </button>
        <span className="text-xs text-neutral-500">
          Creates a new run with fresh evidence. Earlier runs are kept unchanged.
        </span>
      </div>

      {runs.length > 1 && <History runs={runs} currentId={current?.id} onSelect={inspect} />}
    </div>
  );
}

function History({
  runs,
  currentId,
  onSelect,
}: {
  runs: InvestigationRunSummary[];
  currentId: string | undefined;
  onSelect: (id: string) => void;
}) {
  return (
    <details className="rounded border border-neutral-300 p-3 dark:border-neutral-700">
      <summary className="cursor-pointer text-xs font-medium tracking-wide text-neutral-500 uppercase">
        Investigation history ({runs.length})
      </summary>
      <ul className="mt-2 space-y-1 text-sm">
        {runs.map((run) => (
          <li key={run.id} className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs whitespace-nowrap text-neutral-500">
              {formatTimestamp(run.created_at)}
            </span>
            <span>{run.prompt_version}</span>
            {run.status !== "succeeded" ? (
              <Badge tone={run.status === "failed" ? "danger" : "info"}>
                {run.status}
              </Badge>
            ) : run.id === currentId ? (
              <Badge tone="info">current</Badge>
            ) : (
              <button
                type="button"
                onClick={() => onSelect(run.id)}
                className="text-xs underline underline-offset-2"
              >
                inspect
              </button>
            )}
            {run.recommended_action && (
              <span className="text-xs text-neutral-500">
                → {run.recommended_action.replace(/_/g, " ")}
              </span>
            )}
            {run.abstained && <span className="text-xs text-neutral-500">→ abstained</span>}
          </li>
        ))}
      </ul>
    </details>
  );
}

function RunningNotice() {
  return (
    <div className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
      <p className="text-sm font-medium">Investigating…</p>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        Evidence has been collected and sent to the model in one request. This usually
        takes several seconds. The result is stored, so this only happens when asked for.
      </p>
    </div>
  );
}

function ErrorNote({ message }: { message: string }) {
  return (
    <p className="rounded border border-red-300 p-3 text-sm text-red-700 dark:border-red-900 dark:text-red-400">
      {message}
    </p>
  );
}
