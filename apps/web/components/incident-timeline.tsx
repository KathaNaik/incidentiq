import { Badge } from "@/components/badge";
import type { EvidenceItem, IncidentAction, Ticket } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";

type Entry = {
  at: string;
  actor: "system" | "reporter" | "model" | "human";
  label: string;
  detail: string;
};

const ACTOR_TONE = {
  system: "neutral",
  reporter: "info",
  model: "warn",
  human: "danger",
} as const;

const ACTOR_LABEL = {
  system: "Operations",
  reporter: "Reporter",
  model: "AI model",
  human: "Operator",
} as const;

/**
 * A chronological view assembled from evidence that already exists.
 *
 * Every entry carries a timestamp taken from a record — a ticket's creation time, a
 * deployment's ship time, a health snapshot, an audit event. Nothing is placed on this
 * timeline that the system cannot point at, and an evidence item with no timestamp is
 * omitted rather than given a plausible one.
 */
export function IncidentTimeline({
  tickets,
  evidence,
  action,
}: {
  tickets: Ticket[];
  evidence: EvidenceItem[];
  action: IncidentAction | null;
}) {
  const entries: Entry[] = [];

  for (const item of evidence) {
    if (!item.observed_at) continue;
    if (item.kind === "deployment") {
      entries.push({
        at: item.observed_at,
        actor: "system",
        label: "Deployment shipped",
        detail: item.summary,
      });
    } else if (item.kind === "health") {
      entries.push({
        at: item.observed_at,
        actor: "system",
        label: "Service health observed",
        detail: item.summary,
      });
    } else if (item.kind === "error") {
      entries.push({
        at: item.observed_at,
        actor: "system",
        label: "Error signature first seen",
        detail: item.summary,
      });
    }
  }

  for (const ticket of tickets) {
    entries.push({
      at: ticket.created_at,
      actor: "reporter",
      label: "Ticket filed",
      detail: `${ticket.id} — ${ticket.title}`,
    });
  }

  if (action) {
    entries.push({
      at: action.created_at,
      actor: "model",
      label: "Remediation recommended",
      detail: `${action.action_type.replace(/_/g, " ")} — proposed for review`,
    });
    if (action.approval) {
      entries.push({
        at: action.approval.decided_at,
        actor: "human",
        label: action.approval.approved ? "Operator approved" : "Operator rejected",
        detail: action.approval.actor_id,
      });
    }
    if (action.execution) {
      entries.push({
        at: action.execution.executed_at,
        actor: "system",
        label: action.execution.succeeded
          ? "Simulated execution succeeded"
          : "Simulated execution failed",
        detail: action.execution.summary,
      });
    }
  }

  entries.sort((a, b) => a.at.localeCompare(b.at));

  if (entries.length === 0) {
    return (
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        No timestamped evidence is available for this incident yet.
      </p>
    );
  }

  return (
    <ol className="space-y-0">
      {entries.map((entry, index) => (
        <li
          key={`${entry.at}-${entry.label}-${index}`}
          className="flex gap-3 border-l border-neutral-300 pb-3 pl-4 last:pb-0 dark:border-neutral-700"
        >
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs whitespace-nowrap text-neutral-500">
                {formatTimestamp(entry.at)}
              </span>
              <Badge tone={ACTOR_TONE[entry.actor]}>{ACTOR_LABEL[entry.actor]}</Badge>
              <span className="text-sm font-medium">{entry.label}</span>
            </div>
            <p className="mt-0.5 text-sm text-neutral-600 dark:text-neutral-400">
              {entry.detail}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
