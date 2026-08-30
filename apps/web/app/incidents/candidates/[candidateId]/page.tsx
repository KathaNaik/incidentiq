import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { ApiError } from "@/components/api-error";
import { Badge } from "@/components/badge";
import { IncidentTimeline } from "@/components/incident-timeline";
import { InvestigationPanel } from "@/components/investigation-panel";
import { InvestigationPending } from "@/components/investigation-pending";
import { Section } from "@/components/section";
import { SimilarIncidents } from "@/components/similar-incidents";
import {
  load,
  fetchCandidates,
  fetchServices,
  fetchSimilarIncidents,
  fetchTickets,
  fetchInvestigationHistory,
  fetchLatestInvestigation,
  type CandidateIncident,
  type CorrelationMode,
  type Ticket,
} from "@/lib/api";
import { formatTimestamp, serviceLabel, serviceNames } from "@/lib/format";

export const dynamic = "force-dynamic";

/**
 * The incident detail page: the whole product, in order.
 *
 * Read top to bottom it is the transformation itself — reports arrive, correlation
 * explains why it grouped them, evidence is laid out, precedent is shown as precedent,
 * the model hypothesises, deterministic policy rules on the proposal, and a human
 * decides. The section numbering exists so that order is visible rather than implied.
 *
 * Loading this page reads only. Since M13 the investigation section fetches whatever run
 * was stored and renders a Run button when there is not one — opening an incident no
 * longer spends eleven seconds and a set of tokens, and a reload no longer risks showing
 * a different answer than the one the operator was just reading.
 */
export default async function CandidatePage({
  params,
  searchParams,
}: PageProps<"/incidents/candidates/[candidateId]">) {
  const [{ candidateId }, query] = await Promise.all([params, searchParams]);
  const mode: CorrelationMode =
    query.mode === "semantic" ? "semantic" : "deterministic";

  const result = await load(async () => {
    const [correlation, tickets, services] = await Promise.all([
      fetchCandidates(mode),
      fetchTickets(),
      fetchServices(),
    ]);
    return { correlation, tickets, services };
  });

  if (!result.ok) {
    return (
      <div className="space-y-6">
        <BackLink />
        <ApiError error={result.error} />
      </div>
    );
  }

  const candidate = result.data.correlation.candidates.find(
    (item) => item.id === candidateId,
  );
  if (!candidate) notFound();

  const names = serviceNames(result.data.services);
  const byId = new Map(result.data.tickets.map((ticket) => [ticket.id, ticket]));
  const members = candidate.ticket_ids
    .map((id) => byId.get(id))
    .filter((ticket) => ticket !== undefined);

  return (
    <div className="space-y-8">
      <BackLink />

      <Overview
        candidate={candidate}
        serviceName={serviceLabel(names, candidate.service_id)}
        version={result.data.correlation.version}
        mode={mode}
      />

      <Section
        step={1}
        title="Correlated reports"
        subtitle={`${members.length} tickets that correlation believes describe one underlying problem.`}
      >
        <ul className="divide-y divide-neutral-200 rounded border border-neutral-300 dark:divide-neutral-800 dark:border-neutral-700">
          {members.map((ticket) => (
            <TicketRow key={ticket.id} ticket={ticket} />
          ))}
        </ul>
      </Section>

      <Section
        step={2}
        title="Why these were grouped"
        subtitle="Deterministic correlation signals, with their weights. No model was involved in this decision."
      >
        <div className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
          <ul className="space-y-1 text-sm">
            {candidate.supporting_signals.map((signal) => (
              <li key={`s-${signal.component}-${signal.detail}`}>
                <span className="text-green-700 dark:text-green-500">+</span>{" "}
                {signal.detail}{" "}
                <span className="text-xs text-neutral-500">
                  ({signal.component}, weight {signal.weight})
                </span>
              </li>
            ))}
            {candidate.conflicting_signals.length === 0 ? (
              <li className="text-neutral-500">No conflicting evidence.</li>
            ) : (
              candidate.conflicting_signals.map((signal) => (
                <li key={`c-${signal.component}-${signal.detail}`}>
                  <span className="text-amber-700 dark:text-amber-500">−</span>{" "}
                  {signal.detail}{" "}
                  <span className="text-xs text-neutral-500">({signal.component})</span>
                </li>
              ))
            )}
          </ul>

          <details className="mt-3">
            <summary className="cursor-pointer text-xs font-medium tracking-wide text-neutral-500 uppercase">
              Pairwise scores ({candidate.member_pairs.length})
            </summary>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-neutral-500">
                  <tr>
                    <th className="py-1 pr-4 font-medium">Pair</th>
                    <th className="py-1 pr-4 font-medium">Score</th>
                    <th className="py-1 pr-4 font-medium">Content</th>
                    <th className="py-1 pr-4 font-medium">Time</th>
                    <th className="py-1 font-medium">Apart</th>
                  </tr>
                </thead>
                <tbody>
                  {candidate.member_pairs.map((pair) => (
                    <tr
                      key={`${pair.ticket_a}-${pair.ticket_b}`}
                      className="border-t border-neutral-200 dark:border-neutral-800"
                    >
                      <td className="py-1 pr-4 font-mono text-xs">
                        {pair.ticket_a} · {pair.ticket_b}
                      </td>
                      <td className="py-1 pr-4 tabular-nums">{pair.score}</td>
                      <td className="py-1 pr-4 tabular-nums">{pair.content_score}</td>
                      <td className="py-1 pr-4 tabular-nums">{pair.time_score}</td>
                      <td className="py-1 tabular-nums">{pair.minutes_apart} min</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </div>
      </Section>

      <Suspense fallback={<PrecedentPending />}>
        <Precedent candidateId={candidateId} mode={mode} />
      </Suspense>

      <Suspense fallback={<InvestigationSection pending />}>
        <StoredInvestigation
          candidateId={candidateId}
          serviceId={candidate.service_id}
          tickets={members}
        />
      </Suspense>
    </div>
  );
}

// --- overview ---------------------------------------------------------------------------

function Overview({
  candidate,
  serviceName,
  version,
  mode,
}: {
  candidate: CandidateIncident;
  serviceName: string;
  version: string;
  mode: CorrelationMode;
}) {
  return (
    <header className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <h1 className="text-xl font-semibold">{serviceName}</h1>
        <span className="font-mono text-xs text-neutral-500">{candidate.id}</span>
      </div>

      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Affected service" value={serviceName} />
        <Field
          label="Signature"
          value={
            candidate.issue_type
              ? candidate.issue_type.replace(/_/g, " ")
              : "unclassified"
          }
        />
        <Field label="Correlated reports" value={String(candidate.ticket_count)} />
        <Field label="First seen" value={formatTimestamp(candidate.first_seen)} />
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={candidate.confidence === "high" ? "danger" : "warn"}>
          {candidate.confidence} correlation confidence
        </Badge>
        <Badge>score {candidate.score}</Badge>
        <Badge>{version}</Badge>
        {candidate.distinct_reporters !== null && (
          <span className="text-xs text-neutral-500">
            {candidate.distinct_reporters} distinct reporters
          </span>
        )}
      </div>

      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Proposed by the <strong>{mode}</strong> correlation baseline —{" "}
        {mode === "semantic"
          ? "metadata rules plus embedding similarity, with the same guardrails"
          : "phrase and metadata rules, no model"}
        . This is a proposal for a human to confirm, not a declared incident.
      </p>
    </header>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs tracking-wide text-neutral-500 uppercase">{label}</dt>
      <dd className="mt-0.5 font-medium">{value}</dd>
    </div>
  );
}

function TicketRow({ ticket }: { ticket: Ticket }) {
  return (
    <li className="p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs whitespace-nowrap text-neutral-500">
          {formatTimestamp(ticket.created_at)}
        </span>
        <Link
          href={`/tickets/${ticket.id}`}
          className="text-sm font-medium underline underline-offset-2"
        >
          {ticket.title}
        </Link>
        <span className="font-mono text-xs text-neutral-500">{ticket.id}</span>
        {ticket.reported_by && (
          <span className="text-xs text-neutral-500">· {ticket.reported_by}</span>
        )}
      </div>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        {ticket.description}
      </p>
    </li>
  );
}

// --- streamed sections --------------------------------------------------------------------

async function Precedent({
  candidateId,
  mode,
}: {
  candidateId: string;
  mode: CorrelationMode;
}) {
  const similar = await load(() => fetchSimilarIncidents(candidateId, mode));

  return (
    <Section
      step={3}
      title="Historical precedent"
      subtitle="Past incidents that resembled this one. Matching is on symptoms only — a historical cause is a fact about that incident, never a finding about this one."
    >
      {similar.ok ? (
        similar.data.hits.length > 0 ? (
          <SimilarIncidents result={similar.data} />
        ) : (
          <EmptyPanel
            title="No similar past incidents"
            detail="Nothing in the historical corpus resembles this incident closely enough to show. That is a normal result, not a failure."
          />
        )
      ) : (
        <EmptyPanel
          title="Historical retrieval unavailable"
          detail={similar.error}
        />
      )}
    </Section>
  );
}

function PrecedentPending() {
  return (
    <Section step={3} title="Historical precedent">
      <div className="rounded border border-neutral-300 p-4 text-sm text-neutral-500 dark:border-neutral-700">
        Searching the historical corpus…
      </div>
    </Section>
  );
}

async function StoredInvestigation({
  candidateId,
  serviceId,
  tickets,
}: {
  candidateId: string;
  serviceId: string | null;
  tickets: Ticket[];
}) {
  // Reads only. Rendering this page never spends a model call — that is the change M13
  // exists for, and it is why both of these are GETs.
  const [latest, history] = await Promise.all([
    load(() => fetchLatestInvestigation(candidateId)),
    load(() => fetchInvestigationHistory(candidateId)),
  ]);

  if (!latest.ok) {
    return (
      <InvestigationSection>
        <EmptyPanel
          title="Investigation state unavailable"
          detail={latest.error}
          note="Everything above is deterministic and unaffected."
        />
      </InvestigationSection>
    );
  }

  const evidence = latest.data?.current?.result?.evidence ?? [];

  return (
    <>
      <InvestigationSection>
        <InvestigationPanel
          incidentId={candidateId}
          serviceId={serviceId}
          initial={latest.data}
          history={history.ok ? history.data : []}
        />
      </InvestigationSection>

      <Section
        step={5}
        title="Timeline"
        subtitle="Assembled from timestamped evidence. Nothing appears here that the system cannot point at."
      >
        <IncidentTimeline tickets={tickets} evidence={evidence} action={null} />
      </Section>
    </>
  );
}

function InvestigationSection({
  pending = false,
  children,
}: {
  pending?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <Section
      step={4}
      title="AI investigation"
      subtitle="Observed evidence and model hypothesis are kept visually separate. Every citation is validated against the evidence registry before it reaches this page."
    >
      {pending ? <InvestigationPending /> : children}
    </Section>
  );
}

function EmptyPanel({
  title,
  detail,
  note,
}: {
  title: string;
  detail: string;
  note?: string;
}) {
  return (
    <div className="rounded border border-dashed border-neutral-300 p-4 dark:border-neutral-700">
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">{detail}</p>
      {note && <p className="mt-1 text-xs text-neutral-500">{note}</p>}
    </div>
  );
}

function BackLink() {
  return (
    <p className="text-sm">
      <Link className="underline underline-offset-2" href="/incidents">
        ← All incidents
      </Link>
    </p>
  );
}
