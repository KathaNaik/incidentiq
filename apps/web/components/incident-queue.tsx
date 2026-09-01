import Link from "next/link";

import { Badge } from "@/components/badge";
import type { IncidentAction, RuntimeCandidate } from "@/lib/api";
import { formatTimestamp, serviceLabel } from "@/lib/format";

type Tone = "neutral" | "info" | "warn" | "danger";

const ACTION_LABELS: Record<string, { label: string; tone: Tone }> = {
  proposed: { label: "Policy pending", tone: "info" },
  awaiting_approval: { label: "Awaiting approval", tone: "warn" },
  approved: { label: "Approved — not executed", tone: "warn" },
  executing: { label: "Executing", tone: "info" },
  succeeded: { label: "Executed", tone: "info" },
  failed: { label: "Execution failed", tone: "danger" },
  rejected: { label: "Rejected by operator", tone: "neutral" },
  policy_rejected: { label: "Blocked by policy", tone: "danger" },
};

/**
 * The incident queue — the operator's entry point.
 *
 * Ordered by correlation confidence then size, so the case worth opening first is at the
 * top without anything being marked as a demo. A row carries enough to triage from the
 * list: what broke, how many people reported it, how sure correlation is, and whether an
 * action is already waiting on a human.
 */
export function IncidentQueue({
  candidates,
  version,
  services,
  actions,
}: {
  candidates: RuntimeCandidate[];
  version: string;
  services: Map<string, string>;
  actions: IncidentAction[];
}) {
  const rank = { high: 0, medium: 1, low: 2 } as const;
  const ordered = [...candidates].sort(
    (a, b) =>
      rank[a.confidence] - rank[b.confidence] || b.ticket_count - a.ticket_count,
  );

  // Latest action per incident: the row shows where the workflow actually stands.
  const latest = new Map<string, IncidentAction>();
  for (const action of actions) latest.set(action.incident_id, action);

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
          Incident queue
        </h2>
        <span className="text-xs text-neutral-500">
          groups the system proposed from the reports it received — open one to
          investigate it
        </span>
        <span
          className="font-mono text-[11px] text-neutral-400 dark:text-neutral-600"
          title="The correlation version that produced these groupings"
        >
          {version}
        </span>
      </div>

      {ordered.length === 0 ? (
        <div className="rounded border border-dashed border-neutral-300 p-6 text-center dark:border-neutral-700">
          <p className="text-sm font-medium">No candidate incidents</p>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Correlation found no group of tickets that looks like one underlying problem.
            That is a normal quiet state, not an error.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded border border-neutral-300 dark:border-neutral-700">
          <table className="w-full text-sm">
            <thead className="border-b border-neutral-300 text-left text-xs text-neutral-500 dark:border-neutral-700">
              <tr>
                <th className="px-3 py-2 font-medium">Service</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Reports</th>
                <th className="px-3 py-2 font-medium">First seen</th>
                <th className="px-3 py-2 font-medium">Agreement</th>
                <th className="px-3 py-2 font-medium">Workflow</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
              {ordered.map((candidate) => {
                const action = latest.get(candidate.id);
                const state = action ? ACTION_LABELS[action.status] : null;
                return (
                  <tr key={candidate.id} className="align-top">
                    <td className="px-3 py-2 font-medium">
                      <Link
                        href={`/incidents/candidates/${candidate.id}`}
                        className="underline underline-offset-2"
                      >
                        {serviceLabel(services, candidate.service_id)}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-neutral-600 dark:text-neutral-400">
                      {candidate.issue_type
                        ? candidate.issue_type.replace(/_/g, " ")
                        : "unclassified"}
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {candidate.ticket_count}
                      {candidate.distinct_reporters !== null && (
                        <span className="text-xs text-neutral-500">
                          {" "}
                          / {candidate.distinct_reporters}{" "}
                          {candidate.distinct_reporters === 1 ? "reporter" : "reporters"}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs whitespace-nowrap text-neutral-500">
                      {formatTimestamp(candidate.first_seen)}
                    </td>
                    <td className="px-3 py-2">
                      <Badge
                        tone={
                          candidate.confidence === "high"
                            ? "danger"
                            : candidate.confidence === "medium"
                              ? "warn"
                              : "neutral"
                        }
                      >
                        {candidate.confidence}
                      </Badge>
                      <span
                        className="ml-1 text-xs text-neutral-500 tabular-nums"
                        title="Mean agreement between the reports in this group, 0 to 1. Higher means they look more alike."
                      >
                        {candidate.score.toFixed(2)} / 1.00
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {state ? (
                        <Badge tone={state.tone}>{state.label}</Badge>
                      ) : (
                        <span className="text-xs text-neutral-500">
                          not investigated yet
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
