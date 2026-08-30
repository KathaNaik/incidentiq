"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/badge";
import { CorrelationPath } from "@/components/correlation-path";
import { submitTicket, type TicketIntakeResult } from "@/lib/api";

/**
 * The operational intake form.
 *
 * **This is a typed runtime form, not an integration.** Nothing here talks to ServiceNow,
 * Slack, or email — IncidentIQ has no third-party ticketing connection, and this form
 * should not be read as implying one.
 *
 * Submitting posts the real endpoint and renders exactly what came back. Triage and
 * correlation are decided by the server; the form sends neither, and no model is called.
 */
export function TicketIntakeForm({ services }: { services: { id: string; name: string }[] }) {
  const router = useRouter();
  const [result, setResult] = useState<TicketIntakeResult | null>(null);
  const [replayed, setReplayed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const observed = String(form.get("created_at") || "");

    setBusy(true);
    setError(null);
    try {
      const response = await submitTicket({
        external_id: String(form.get("external_id") || "").trim(),
        title: String(form.get("title") || "").trim(),
        description: String(form.get("description") || "").trim(),
        created_at: observed ? new Date(observed).toISOString() : undefined,
        reported_service_id: String(form.get("service") || "") || null,
      });
      setResult(response.result);
      setReplayed(response.replayed);
      // The dashboard and ticket list are server-rendered; refresh so the new state shows.
      router.refresh();
    } catch (caught) {
      setResult(null);
      setError(caught instanceof Error ? caught.message : "Submission failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3 rounded border border-neutral-300 p-4 dark:border-neutral-700">
      <div>
        <h2 className="text-sm font-medium">Submit a report</h2>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          A typed intake API, not a connection to a third-party ticketing system. The
          server triages the report and compares it against incidents that are still open.
          No language model is involved.
        </p>
      </div>

      <form onSubmit={onSubmit} className="grid gap-3 sm:grid-cols-2">
        <Field label="External id" hint="Your reference. Resubmitting it is a no-op.">
          <input
            name="external_id"
            required
            placeholder="INC-2026-0042"
            className="w-full rounded border border-neutral-300 bg-transparent px-2 py-1 text-sm dark:border-neutral-700"
          />
        </Field>
        <Field label="Observed at" hint="When the problem was seen, not when you filed it.">
          <input
            name="created_at"
            type="datetime-local"
            className="w-full rounded border border-neutral-300 bg-transparent px-2 py-1 text-sm dark:border-neutral-700"
          />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Title">
            <input
              name="title"
              required
              placeholder="Sign-in through the identity provider is failing"
              className="w-full rounded border border-neutral-300 bg-transparent px-2 py-1 text-sm dark:border-neutral-700"
            />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Description">
            <textarea
              name="description"
              rows={3}
              placeholder="What was observed, including any error text."
              className="w-full rounded border border-neutral-300 bg-transparent px-2 py-1 text-sm dark:border-neutral-700"
            />
          </Field>
        </div>
        <Field label="Service" hint="Optional. Triage forms its own view either way.">
          <select
            name="service"
            defaultValue=""
            className="w-full rounded border border-neutral-300 bg-transparent px-2 py-1 text-sm dark:border-neutral-700"
          >
            <option value="">not stated</option>
            {services.map((service) => (
              <option key={service.id} value={service.id}>
                {service.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="flex items-end">
          <button
            type="submit"
            disabled={busy}
            className="rounded border border-neutral-400 px-3 py-1 text-sm disabled:opacity-50 dark:border-neutral-600"
          >
            {busy ? "Submitting…" : "Submit report"}
          </button>
        </div>
      </form>

      {error && (
        <p className="rounded border border-red-300 p-3 text-sm text-red-700 dark:border-red-900 dark:text-red-400">
          {error}
        </p>
      )}

      {result && <Outcome result={result} replayed={replayed} />}
    </section>
  );
}

function Outcome({
  result,
  replayed,
}: {
  result: TicketIntakeResult;
  replayed: boolean;
}) {
  const { triage, correlation } = result;
  const attached = correlation.candidate_id !== null;

  return (
    <div className="rounded border border-neutral-400 p-3 dark:border-neutral-600">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">
          {replayed ? "Already received" : "Ticket accepted"}
        </span>
        <code className="text-xs text-neutral-500">{result.ticket.id}</code>
        {replayed && <Badge>idempotent replay</Badge>}
      </div>

      <dl className="mt-2 space-y-1 text-sm">
        <Row label="Triage">
          {[triage.service_id, triage.priority, triage.issue_type]
            .map((value) => value ?? "—")
            .join(" / ")}{" "}
          <span className="text-xs text-neutral-500">({triage.version})</span>
        </Row>
        <Row label="Correlation">
          {attached ? (
            <>
              <Badge tone="info">
                {correlation.created_new_candidate ? "new incident" : "attached"}
              </Badge>{" "}
              <code className="text-xs">{correlation.candidate_id}</code>
              {correlation.score !== null && (
                <span className="text-xs text-neutral-500">
                  {" "}
                  score {correlation.score} · {correlation.confidence}
                </span>
              )}
            </>
          ) : (
            <>
              <Badge>{correlation.outcome.replace(/_/g, " ")}</Badge>{" "}
              <span className="text-neutral-600 dark:text-neutral-400">
                No strong incident match — the report stands on its own.
              </span>
            </>
          )}
        </Row>
      </dl>
      <p className="mt-2 text-xs text-neutral-500">{correlation.reason}</p>

      <CorrelationPath correlation={correlation} />
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="text-xs tracking-wide text-neutral-500 uppercase">{label}</span>
      <span className="mt-1 block">{children}</span>
      {hint && <span className="mt-0.5 block text-xs text-neutral-500">{hint}</span>}
    </label>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap gap-2">
      <dt className="text-xs tracking-wide text-neutral-500 uppercase">{label}</dt>
      <dd className="flex-1">{children}</dd>
    </div>
  );
}
