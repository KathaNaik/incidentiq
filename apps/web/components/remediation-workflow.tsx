"use client";

import { useState } from "react";

import { Badge } from "@/components/badge";
import {
  approveAction,
  executeAction,
  fetchActionAudit,
  proposeAction,
  rejectAction,
  type AuditEvent,
  type IncidentAction,
  type InvestigationResult,
} from "@/lib/api";
import { formatTimestamp } from "@/lib/format";

const ACTOR_LABELS: Record<string, string> = {
  model: "AI model",
  system: "IncidentIQ",
  human: "Operator",
};

const EVENT_LABELS: Record<string, string> = {
  recommendation_received: "AI recommended an action",
  action_proposed: "System proposed the action",
  policy_evaluated: "System evaluated policy",
  approval_granted: "Operator approved",
  approval_rejected: "Operator rejected",
  execution_started: "Simulated execution started",
  execution_succeeded: "Simulated execution succeeded",
  execution_failed: "Simulated execution failed",
  execution_skipped_idempotent: "Repeat request — already executed, not run again",
};

/**
 * The approval workflow.
 *
 * Two separate human moments, deliberately: approving a plan and running it are
 * different decisions, and the second button only appears after the first. Neither
 * happens automatically, whatever the model's confidence was.
 *
 * Button visibility follows the action's server-side status, but it is not the control
 * — the API refuses illegal transitions regardless of what this component renders.
 */
export function RemediationWorkflow({
  result: investigation,
  serviceId,
}: {
  result: InvestigationResult;
  serviceId: string | null;
}) {
  const [action, setAction] = useState<IncidentAction | null>(null);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recommendation = investigation.output.remediation;

  if (!recommendation) {
    return (
      <section className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
        <h3 className="text-sm font-medium">No remediation recommended</h3>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          The investigation did not propose a consequential action, so there is nothing
          to approve. That is a valid outcome, not a missing feature.
        </p>
      </section>
    );
  }

  async function run(work: () => Promise<{ action: IncidentAction }>) {
    setBusy(true);
    setError(null);
    try {
      const result = await work();
      setAction(result.action);
      setAudit(await fetchActionAudit(result.action.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  const status = action?.status;
  const policy = action?.policy;

  return (
    <section className="space-y-3 rounded border border-amber-300 p-4 dark:border-amber-900">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium">Recommended remediation</h3>
        <Badge tone={recommendation.risk === "high" ? "danger" : "warn"}>
          model-stated risk: {recommendation.risk}
        </Badge>
        {action && (
          <Badge tone={action.risk === "high" ? "danger" : "warn"}>
            policy risk: {action.risk}
          </Badge>
        )}
      </div>
      <p className="text-sm text-neutral-700 dark:text-neutral-300">
        {recommendation.description}
      </p>
      <ul className="space-y-0.5 text-xs text-neutral-500">
        {recommendation.supporting_evidence_ids.map((id) => (
          <li key={id}>
            <code>{id}</code>
          </li>
        ))}
      </ul>

      {!action && (
        <button
          type="button"
          disabled={busy}
          onClick={() => run(() => proposeAction(investigation.incident_id, investigation, serviceId))}
          className="rounded border border-neutral-400 px-3 py-1 text-sm disabled:opacity-50 dark:border-neutral-600"
        >
          {busy ? "Checking policy…" : "Check application policy"}
        </button>
      )}

      {policy && (
        <div className="rounded border border-neutral-300 p-3 dark:border-neutral-700">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-medium">Application policy</h4>
            <Badge tone={policy.eligible ? "info" : "danger"}>
              {policy.eligible ? "Eligible for approval" : "Not eligible"}
            </Badge>
            <span className="text-xs text-neutral-500">
              {policy.required_approvals} approval required · deterministic, no model
              involved
            </span>
          </div>
          <ul className="mt-2 space-y-1 text-sm">
            {policy.reasons.map((reason) => (
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
                {reason.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      {status && (
        <p className="text-sm">
          Status <Badge>{status.replace(/_/g, " ")}</Badge>
        </p>
      )}

      {action && status === "awaiting_approval" && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => run(() => approveAction(action.id))}
            className="rounded border border-green-600 px-3 py-1 text-sm text-green-700 disabled:opacity-50 dark:text-green-500"
          >
            Approve
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => run(() => rejectAction(action.id))}
            className="rounded border border-neutral-400 px-3 py-1 text-sm disabled:opacity-50 dark:border-neutral-600"
          >
            Reject
          </button>
        </div>
      )}

      {action && status === "approved" && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => run(() => executeAction(action.id))}
            className="rounded border border-amber-600 px-3 py-1 text-sm text-amber-800 disabled:opacity-50 dark:text-amber-400"
          >
            Execute simulated {action.action_type.replace(/_/g, " ")}
          </button>
          <span className="text-xs text-neutral-500">
            Approval and execution are separate steps on purpose.
          </span>
        </div>
      )}

      {action?.execution && (
        <div className="rounded border border-green-300 p-3 dark:border-green-900">
          <p className="text-sm font-medium">
            {action.execution.succeeded ? "✓" : "✗"} {action.execution.summary}
          </p>
          <p className="mt-1 text-xs text-neutral-500">
            Simulated — no infrastructure was contacted.{" "}
            {formatTimestamp(action.execution.executed_at)}
          </p>
          <ul className="mt-2 space-y-0.5 text-sm text-neutral-700 dark:text-neutral-300">
            {action.execution.details.map((detail) => (
              <li key={detail}>{detail}</li>
            ))}
          </ul>
        </div>
      )}

      {status === "policy_rejected" && (
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          The model recommended this, and the application declined to make it
          actionable. There is no approval path for it.
        </p>
      )}

      {error && (
        <p className="rounded border border-red-300 p-2 text-sm text-red-700 dark:border-red-900 dark:text-red-400">
          {error}
        </p>
      )}

      {audit.length > 0 && <AuditTimeline events={audit} />}
    </section>
  );
}

function AuditTimeline({ events }: { events: AuditEvent[] }) {
  return (
    <div>
      <h4 className="text-xs font-medium tracking-wide text-neutral-500 uppercase">
        Audit trail
      </h4>
      <ol className="mt-2 space-y-1 text-sm">
        {events.map((event) => (
          <li key={event.id} className="flex flex-wrap gap-2">
            <span className="font-mono text-xs text-neutral-500">
              {new Date(event.occurred_at).toISOString().slice(11, 19)}
            </span>
            <Badge tone={event.actor_type === "human" ? "info" : "neutral"}>
              {ACTOR_LABELS[event.actor_type] ?? event.actor_type}
            </Badge>
            <span>{EVENT_LABELS[event.event_type] ?? event.event_type}</span>
            <span className="text-xs text-neutral-500">{event.actor_id}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
