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
  investigationRunId,
  readOnly = false,
}: {
  result: InvestigationResult;
  serviceId: string | null;
  /** The stored run this recommendation came from. The action is linked to it. */
  investigationRunId: string;
  readOnly?: boolean;
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

      {readOnly && (
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          This is a superseded investigation. Its recommendation is kept as a record of
          what the model said at the time; actions are proposed from the current run.
        </p>
      )}

      {!action && !readOnly && (
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            run(() =>
              proposeAction(investigation.incident_id, investigationRunId, serviceId),
            )
          }
          className="rounded border border-neutral-400 px-3 py-1 text-sm disabled:opacity-50 dark:border-neutral-600"
        >
          {busy ? "Checking policy…" : "Check application policy"}
        </button>
      )}

      {policy && (
        <div className="rounded border border-neutral-400 p-3 dark:border-neutral-600">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-medium">
              Application policy — {action?.action_type.replace(/_/g, " ")}
            </h4>
            <Badge tone={policy.eligible ? "info" : "danger"}>
              {policy.eligible ? "Eligible for approval" : "Not eligible"}
            </Badge>
            <Badge tone={policy.effective_risk === "high" ? "danger" : "warn"}>
              risk {policy.effective_risk}
            </Badge>
          </div>
          <p className="mt-1 text-xs text-neutral-500">
            {policy.reasons.filter((r) => r.passed).length}/{policy.reasons.length}{" "}
            checks passed · {policy.required_approvals} human approval required.{" "}
            <strong>This is application code, not a second AI opinion.</strong> Each
            check is a predicate over typed records, and the risk level is assigned here
            rather than taken from the model.
          </p>
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
                <span className="font-mono text-xs text-neutral-500">
                  {reason.check}
                </span>{" "}
                {reason.detail}
                {reason.evidence_ids.length > 0 && (
                  <span className="text-xs text-neutral-500">
                    {" "}
                    [{reason.evidence_ids.join(", ")}]
                  </span>
                )}
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

      {(status === "policy_rejected" ||
        (action && !action.policy.eligible && status !== "rejected")) && (
        <div className="rounded border border-red-300 p-3 dark:border-red-900">
          <p className="text-sm font-medium">No approval path for this action</p>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            The model recommended it and the application declined to make it actionable,
            for the reasons marked ✗ above. There is deliberately no override button: a
            policy an operator can click past is not a policy.
          </p>
        </div>
      )}

      {status === "rejected" && (
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          An operator rejected this action. It cannot be approved afterwards; propose a
          fresh action if the situation changes.
        </p>
      )}

      {action?.execution && !action.execution.succeeded && (
        <div className="rounded border border-red-300 p-3 dark:border-red-900">
          <p className="text-sm font-medium">Simulated execution failed</p>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            The action reached the executor and did not succeed. Nothing was retried
            automatically.
          </p>
        </div>
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

/**
 * The audit trail, read as an actor boundary.
 *
 * The point is not that events happened but *who* caused each one: the model only ever
 * recommends, the system proposes and executes, and every approval is a human. Showing
 * the actor beside each event is what makes that boundary checkable rather than claimed.
 */
function AuditTimeline({ events }: { events: AuditEvent[] }) {
  return (
    <div>
      <h4 className="text-xs font-medium tracking-wide text-neutral-500 uppercase">
        Audit trail
      </h4>
      <p className="mt-1 text-xs text-neutral-500">
        AI recommends → system evaluates policy → human approves → system executes.
        Append-only; nothing here is edited or removed.
      </p>
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
