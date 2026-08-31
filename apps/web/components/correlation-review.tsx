"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/badge";
import {
  CONFIRM_REASONS,
  REJECT_REASONS,
  confirmCorrelationReview,
  rejectCorrelationReview,
  type CorrelationReview,
  type ReviewDecisionResult,
} from "@/lib/api";
import { formatTimestamp } from "@/lib/format";

/**
 * One ambiguous grouping, and the two answers an operator can give it.
 *
 * The buttons say what the decision *means* — "Same incident" and "Different incident" —
 * rather than approve and deny. This is not an approval workflow: nothing is being
 * authorised, a question about the world is being answered, and the answer becomes a
 * training label. A button labelled "Approve" would produce labels whose meaning depended
 * on what the operator thought they were approving.
 *
 * Everything shown here comes from the review's stored snapshot, never from current
 * state. The operator must be looking at exactly what the decision will be recorded
 * against, or the label describes a pairing nobody actually judged.
 */
export function CorrelationReviewCard({
  review,
  onDecided,
}: {
  review: CorrelationReview;
  onDecided?: (result: ReviewDecisionResult) => void;
}) {
  const router = useRouter();
  const [reason, setReason] = useState<string>("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"confirm" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ReviewDecisionResult | null>(null);

  const ticket = review.ticket_snapshot;
  const candidate = review.candidate_snapshot;
  const decided = review.status !== "pending";

  async function decide(kind: "confirm" | "reject") {
    setBusy(kind);
    setError(null);
    try {
      const body = {
        ...(reason ? { reason } : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
      };
      const outcome =
        kind === "confirm"
          ? await confirmCorrelationReview(review.id, body)
          : await rejectCorrelationReview(review.id, body);
      setResult(outcome);
      onDecided?.(outcome);
      // The queue, the dashboard count and the ticket's state all change with this.
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  if (result) {
    return <Outcome review={review} result={result} />;
  }

  if (review.status === "stale") {
    return (
      <section className="space-y-2 rounded border border-amber-300 p-4 dark:border-amber-800">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="warn">Stale</Badge>
          <span className="text-sm font-medium">{ticket.title}</span>
        </div>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          The candidate changed after this review was raised, so the question it asks is
          no longer the one an answer would apply to. A fresh review will be raised
          against the current state.
        </p>
      </section>
    );
  }

  if (decided) {
    return <Decided review={review} />;
  }

  return (
    <section className="space-y-4 rounded border border-neutral-300 p-4 dark:border-neutral-700">
      <header className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="warn">Needs review</Badge>
          <span className="font-mono text-xs text-neutral-500">{review.id}</span>
        </div>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Automatic correlation could not decide this one. It is not a near-duplicate and
          it is not a clear conflict.
        </p>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1">
          <h4 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            Incoming report
          </h4>
          <p className="text-sm font-medium">{ticket.title}</p>
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            {ticket.description}
          </p>
          <p className="font-mono text-xs text-neutral-500">
            {ticket.id} · {formatTimestamp(ticket.created_at)}
            {ticket.service_id ? ` · ${ticket.service_id}` : ""}
          </p>
        </div>

        <div className="space-y-1">
          <h4 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            Proposed incident — {candidate.ticket_count} report
            {candidate.ticket_count === 1 ? "" : "s"}
          </h4>
          <p className="text-sm font-medium">{candidate.title}</p>
          <ul className="space-y-1">
            {candidate.members.map((member) => (
              <li key={member.id} className="text-sm">
                <span className="text-neutral-600 dark:text-neutral-400">
                  {member.title}
                </span>
                <span className="ml-1 font-mono text-xs text-neutral-500">
                  {member.id} · {formatTimestamp(member.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <Signals review={review} />

      <div className="space-y-3 border-t border-neutral-200 pt-3 dark:border-neutral-800">
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={`reason-${review.id}`} className="text-sm">
            Reason
          </label>
          <select
            id={`reason-${review.id}`}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="rounded border border-neutral-300 bg-transparent px-2 py-1 text-sm dark:border-neutral-700"
          >
            <option value="">Not given</option>
            <optgroup label="If same incident">
              {CONFIRM_REASONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </optgroup>
            <optgroup label="If different incident">
              {REJECT_REASONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </optgroup>
          </select>
        </div>

        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Optional note — what made this clear to you?"
          rows={2}
          maxLength={1000}
          className="w-full rounded border border-neutral-300 bg-transparent px-2 py-1 text-sm dark:border-neutral-700"
        />

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => decide("confirm")}
            disabled={busy !== null}
            className="rounded bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
          >
            {busy === "confirm" ? "Attaching…" : "Same incident"}
          </button>
          <button
            type="button"
            onClick={() => decide("reject")}
            disabled={busy !== null}
            className="rounded border border-neutral-300 px-3 py-1.5 text-sm font-medium disabled:opacity-50 dark:border-neutral-700"
          >
            {busy === "reject" ? "Recording…" : "Different incident"}
          </button>
        </div>

        {error && (
          <p className="text-sm text-red-700 dark:text-red-400" role="alert">
            {error}
          </p>
        )}

        <p className="text-xs text-neutral-500">
          Recorded against a fixed demo operator — this prototype has no authentication.
          The decision is pinned to the candidate exactly as shown above; if it changes
          first, this review goes stale rather than applying your answer to a different
          grouping.
        </p>
      </div>
    </section>
  );
}

/** Why automatic correlation stopped short, in its own words. */
function Signals({ review }: { review: CorrelationReview }) {
  const { reasons, deterministic_score } = review.correlation_snapshot;
  if (reasons.length === 0 && deterministic_score === null) return null;

  return (
    <div className="space-y-1 rounded bg-neutral-50 p-3 dark:bg-neutral-900">
      <h4 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
        What the deterministic pass found
      </h4>
      {deterministic_score !== null && (
        <p className="font-mono text-xs text-neutral-600 dark:text-neutral-400">
          score {deterministic_score.toFixed(4)}
        </p>
      )}
      <ul className="list-inside list-disc space-y-0.5">
        {reasons.map((reason) => (
          <li key={reason} className="text-sm text-neutral-600 dark:text-neutral-400">
            {reason}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Decided({ review }: { review: CorrelationReview }) {
  const same = review.status === "confirmed";
  return (
    <section className="space-y-1 rounded border border-neutral-300 p-4 dark:border-neutral-700">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={same ? "info" : "neutral"}>
          {same ? "Same incident" : "Different incident"}
        </Badge>
        <span className="text-sm font-medium">{review.ticket_snapshot.title}</span>
      </div>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        {review.actor} ·{" "}
        {review.decided_at ? formatTimestamp(review.decided_at) : "unknown time"}
        {review.decision_reason ? ` · ${review.decision_reason.replace(/_/g, " ")}` : ""}
      </p>
      {review.decision_note && (
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          “{review.decision_note}”
        </p>
      )}
    </section>
  );
}

function Outcome({
  review,
  result,
}: {
  review: CorrelationReview;
  result: ReviewDecisionResult;
}) {
  const { attached, candidate, investigation_stale, superseded_review_ids } =
    result.result;

  return (
    <section className="space-y-2 rounded border border-neutral-300 p-4 dark:border-neutral-700">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={attached ? "info" : "neutral"}>
          {attached ? "Same incident" : "Different incident"}
        </Badge>
        <span className="text-sm font-medium">{review.ticket_snapshot.title}</span>
      </div>

      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        {attached && candidate
          ? `Attached to ${candidate.id}, now ${candidate.ticket_count} reports.`
          : "Recorded. The ticket was left where it was — this says it does not belong to that candidate, not that it belongs to nothing."}
      </p>

      {investigation_stale && (
        <p className="text-sm text-amber-700 dark:text-amber-500">
          An existing investigation for this incident predates the report you just
          attached. It is marked stale; re-running it stays your decision.
        </p>
      )}

      {superseded_review_ids.length > 0 && (
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          {superseded_review_ids.length} other pending review
          {superseded_review_ids.length === 1 ? "" : "s"} for this ticket closed — a
          report cannot belong to two mutually exclusive incidents.
        </p>
      )}

      <p className="text-xs text-neutral-500">
        Exported as a Northstar-native label. Nothing is retrained automatically.
      </p>
    </section>
  );
}
