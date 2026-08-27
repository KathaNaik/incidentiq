import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiError } from "@/components/api-error";
import { Badge } from "@/components/badge";
import { load, fetchCandidates, fetchServices, fetchTickets } from "@/lib/api";
import { formatTimestamp, serviceLabel, serviceNames } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function CandidatePage({
  params,
}: PageProps<"/incidents/candidates/[candidateId]">) {
  const { candidateId } = await params;

  const result = await load(async () => {
    const [correlation, tickets, services] = await Promise.all([
      fetchCandidates(),
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
    <div className="space-y-6">
      <BackLink />

      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold">Candidate incident</h1>
          <span className="font-mono text-xs text-neutral-500">{candidate.id}</span>
        </div>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Proposed by the <strong>deterministic correlation baseline</strong> (
          {result.data.correlation.version}) — phrase and metadata rules, no model. This
          is a proposal for a human to confirm, not a declared incident.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={candidate.confidence === "high" ? "danger" : "warn"}>
            {candidate.confidence} confidence
          </Badge>
          <Badge>score {candidate.score}</Badge>
          <Badge>{serviceLabel(names, candidate.service_id)}</Badge>
          {candidate.issue_type && <Badge>{candidate.issue_type.replace(/_/g, " ")}</Badge>}
          <span className="text-xs text-neutral-500">
            {candidate.ticket_count} tickets
            {candidate.distinct_reporters !== null &&
              ` · ${candidate.distinct_reporters} distinct reporters`}
          </span>
        </div>
      </header>

      <section className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
        <h2 className="text-sm font-medium">Evidence</h2>
        <ul className="mt-2 space-y-1 text-sm">
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
            <li className="text-sm text-neutral-500">No conflicting evidence.</li>
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
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
          Timeline
        </h2>
        <ol className="space-y-3">
          {members.map((ticket) => (
            <li
              key={ticket.id}
              className="rounded border border-neutral-300 p-4 dark:border-neutral-700"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-neutral-500">
                  {formatTimestamp(ticket.created_at)}
                </span>
                <Link
                  href={`/tickets/${ticket.id}`}
                  className="font-medium underline underline-offset-2"
                >
                  {ticket.title}
                </Link>
                <span className="font-mono text-xs text-neutral-500">{ticket.id}</span>
              </div>
              <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
                {ticket.description}
              </p>
            </li>
          ))}
        </ol>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
          Pairwise scores
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-neutral-500">
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
      </section>
    </div>
  );
}

function BackLink() {
  return (
    <p className="text-sm">
      <Link className="underline" href="/incidents">
        ← All incidents
      </Link>
    </p>
  );
}
