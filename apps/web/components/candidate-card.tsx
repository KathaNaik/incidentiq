import Link from "next/link";

import { Badge } from "@/components/badge";
import type { CandidateIncident, CorrelationMode } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";

const CONFIDENCE_TONE = {
  high: "danger",
  medium: "warn",
  low: "neutral",
} as const;

/**
 * A proposal, presented as one. The wording avoids "incident detected" because nothing
 * has been confirmed — a person still decides whether this is real.
 */
export function CandidateCard({
  candidate,
  serviceNames,
  mode = "deterministic",
}: {
  candidate: CandidateIncident;
  serviceNames: Map<string, string>;
  mode?: CorrelationMode;
}) {
  return (
    <li className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={CONFIDENCE_TONE[candidate.confidence]}>
          {candidate.confidence} confidence
        </Badge>
        <span className="font-medium">
          {candidate.service_id
            ? (serviceNames.get(candidate.service_id) ?? candidate.service_id)
            : "Mixed services"}
          {candidate.issue_type ? ` — ${candidate.issue_type.replace(/_/g, " ")}` : ""}
        </span>
        <span className="font-mono text-xs text-neutral-500">{candidate.id}</span>
      </div>

      <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
        {candidate.ticket_count} correlated tickets · score {candidate.score} · first
        seen {formatTimestamp(candidate.first_seen)}
        {candidate.distinct_reporters !== null &&
          ` · ${candidate.distinct_reporters} distinct reporters`}
      </p>

      <ul className="mt-3 space-y-1 text-xs text-neutral-600 dark:text-neutral-400">
        {candidate.supporting_signals.map((signal) => (
          <li key={`${signal.component}-${signal.detail}`}>+ {signal.detail}</li>
        ))}
        {candidate.conflicting_signals.map((signal) => (
          <li key={`${signal.component}-${signal.detail}`} className="text-amber-700 dark:text-amber-500">
            − {signal.detail}
          </li>
        ))}
      </ul>

      <p className="mt-3 text-sm">
        <Link
          className="underline"
          href={`/incidents/candidates/${candidate.id}${mode === "semantic" ? "?mode=semantic" : ""}`}
        >
          View candidate
        </Link>
      </p>
    </li>
  );
}
