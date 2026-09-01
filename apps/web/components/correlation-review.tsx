"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/badge";
import { Disclosure } from "@/components/disclosure";
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
 *
 * The default card carries only what the decision needs: the two things being compared,
 * why automation stopped, and the two answers. Full report text, every candidate member,
 * the feature vector and the snapshot fingerprint are one disclosure away — an operator
 * deciding does not need them, and an engineer auditing does.
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

  const signals = review.correlation_snapshot.reasons;
  const score = review.correlation_snapshot.deterministic_score;

  return (
    <section className="space-y-3 rounded border border-neutral-300 p-4 dark:border-neutral-700">
      <header className="flex flex-wrap items-center gap-2">
        <Badge tone="warn">Needs review</Badge>
        {score !== null && (
          <span className="font-mono text-xs text-neutral-500 tabular-nums">
            score {score.toFixed(2)} / 0.60 needed
          </span>
        )}
      </header>

      {/* The question, as two sides of one comparison. Titles and one line of body: enough
          to judge, without making an operator read four full ticket descriptions first. */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="min-w-0">
          <h4 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            Incoming report
          </h4>
          <p className="mt-1 text-sm font-medium">{ticket.title}</p>
          <p className="mt-0.5 line-clamp-2 text-sm text-neutral-600 dark:text-neutral-400">
            {ticket.description}
          </p>
          <p className="mt-1 text-xs text-neutral-500">
            {formatTimestamp(ticket.created_at)}
            {ticket.service_id ? ` · ${ticket.service_id}` : ""}
          </p>
        </div>

        <div className="min-w-0">
          <h4 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            Possible incident
          </h4>
          <p className="mt-1 text-sm font-medium">{candidate.title}</p>
          <p className="mt-0.5 line-clamp-2 text-sm text-neutral-600 dark:text-neutral-400">
            {candidate.members[0]?.title}
          </p>
          <p className="mt-1 text-xs text-neutral-500">
            {candidate.ticket_count} report
            {candidate.ticket_count === 1 ? "" : "s"}
            {candidate.service_id ? ` · ${candidate.service_id}` : ""}
          </p>
        </div>
      </div>

      {signals.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            Why IncidentIQ is unsure
          </h4>
          <ul className="mt-1 space-y-0.5">
            {signals.map((reason) => (
              <li
                key={reason}
                className="flex gap-1.5 text-sm text-neutral-600 dark:text-neutral-400"
              >
                <span aria-hidden className="text-neutral-400 dark:text-neutral-600">
                  {/low|conflict|below/i.test(reason) ? "△" : "✓"}
                </span>
                <span>{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
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

        <label htmlFor={`reason-${review.id}`} className="sr-only">
          Reason
        </label>
        <select
          id={`reason-${review.id}`}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="rounded border border-neutral-300 bg-transparent px-2 py-1.5 text-sm dark:border-neutral-700"
        >
          <option value="">Reason (optional)</option>
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

      {error && (
        <p className="text-sm text-red-700 dark:text-red-400" role="alert">
          {error}
        </p>
      )}

      <Details review={review} note={note} onNote={setNote} />
    </section>
  );
}

/**
 * Everything an engineer needs to audit the decision, and nothing an operator needs to
 * make it.
 *
 * Full ticket text, every candidate member, the exact feature vector, the fingerprint the
 * decision is pinned to, and the version metadata all live here. None of it was deleted;
 * it stopped being the first thing on the page.
 */
function Details({
  review,
  note,
  onNote,
}: {
  review: CorrelationReview;
  note: string;
  onNote: (value: string) => void;
}) {
  const ticket = review.ticket_snapshot;
  const candidate = review.candidate_snapshot;
  const features = Object.entries(review.feature_snapshot);

  return (
    <Disclosure
      summary="Evidence and provenance"
      hint={`${candidate.members.length} reports · ${features.length} features`}
    >
      <div className="space-y-4">
        <div>
          <h5 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            Add a note
          </h5>
          <textarea
            value={note}
            onChange={(event) => onNote(event.target.value)}
            placeholder="What made this clear to you? Optional, stored with the decision."
            rows={2}
            maxLength={1000}
            className="mt-1 w-full rounded border border-neutral-300 bg-transparent px-2 py-1 text-sm dark:border-neutral-700"
          />
        </div>

        <div>
          <h5 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            Incoming report in full
          </h5>
          <p className="mt-1 text-sm font-medium">{ticket.title}</p>
          <p className="mt-0.5 text-sm text-neutral-600 dark:text-neutral-400">
            {ticket.description}
          </p>
          <p className="mt-1 font-mono text-xs text-neutral-500">
            {ticket.id}
            {ticket.external_id ? ` · ${ticket.external_id}` : ""} ·{" "}
            {formatTimestamp(ticket.created_at)} · triage {ticket.triage_version}
          </p>
        </div>

        <div>
          <h5 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            Candidate reports ({candidate.members.length})
          </h5>
          <ul className="mt-1 space-y-2">
            {candidate.members.map((member) => (
              <li key={member.id}>
                <p className="text-sm font-medium">{member.title}</p>
                <p className="text-sm text-neutral-600 dark:text-neutral-400">
                  {member.description}
                </p>
                <p className="font-mono text-xs text-neutral-500">
                  {member.id} · {formatTimestamp(member.created_at)}
                  {member.issue_type ? ` · ${member.issue_type}` : ""}
                </p>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <h5 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            Correlation features
          </h5>
          <div className="mt-1 grid gap-x-4 gap-y-0.5 sm:grid-cols-2">
            {features.map(([name, value]) => (
              <p
                key={name}
                className="flex justify-between gap-2 font-mono text-xs text-neutral-600 dark:text-neutral-400"
              >
                <span>{name}</span>
                <span className="tabular-nums">{value}</span>
              </p>
            ))}
          </div>
        </div>

        <div>
          <h5 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            Decision provenance
          </h5>
          <p className="mt-1 font-mono text-xs break-all text-neutral-500">
            review {review.id} · snapshot {review.candidate_fingerprint}
          </p>
          <p className="font-mono text-xs text-neutral-500">
            {review.correlation_version} · {review.review_policy_version} ·{" "}
            {review.feature_schema}
          </p>
        </div>
      </div>
    </Disclosure>
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
