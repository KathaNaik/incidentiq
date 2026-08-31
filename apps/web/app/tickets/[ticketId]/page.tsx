import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiError } from "@/components/api-error";
import { Badge } from "@/components/badge";
import { TriagePanel } from "@/components/triage-panel";
import { CorrelationReviewCard } from "@/components/correlation-review";
import {
  load,
  fetchCorrelationReviews,
  fetchRuntimeTicket,
  fetchServices,
  fetchTicketTriage,
} from "@/lib/api";
import { formatTimestamp, serviceLabel, serviceNames } from "@/lib/format";

export const dynamic = "force-dynamic";

/**
 * One report, and everything the system decided about it.
 *
 * Two decisions are shown separately because they are separate: what triage predicted
 * from the text, and what correlation did with it. The correlation reason is the stored
 * one — recorded when the ticket arrived, not recomputed now, so a later threshold change
 * cannot rewrite why something was grouped last week.
 */
export default async function TicketPage({
  params,
}: PageProps<"/tickets/[ticketId]">) {
  const { ticketId } = await params;

  const result = await load(async () => {
    const [ticket, services] = await Promise.all([
      fetchRuntimeTicket(ticketId),
      fetchServices(),
    ]);
    return { ticket, services };
  });

  // The ticket renders with or without this; a review is an extra question about it,
  // not part of the record.
  const reviews = await load(() => fetchCorrelationReviews(true));
  const openReviews = reviews.ok
    ? reviews.data.filter((review) => review.ticket_id === ticketId)
    : [];

  if (!result.ok) {
    if (result.error.includes("404")) notFound();
    return (
      <div className="space-y-6">
        <BackLink />
        <ApiError error={result.error} />
      </div>
    );
  }

  const { ticket, services } = result.data;
  const names = serviceNames(services);
  const triage = await load(() => fetchTicketTriage(ticket.id));

  return (
    <div className="space-y-6">
      <BackLink />

      <header className="space-y-2">
        <h1 className="text-xl font-semibold">{ticket.title}</h1>
        <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
          <code>{ticket.external_id ?? ticket.id}</code>
          <Badge>{ticket.source}</Badge>
          <Badge>{ticket.status}</Badge>
          <span>observed {formatTimestamp(ticket.created_at)}</span>
          <span>· received {formatTimestamp(ticket.received_at)}</span>
        </div>
        {ticket.description && (
          <p className="text-sm text-neutral-700 dark:text-neutral-300">
            {ticket.description}
          </p>
        )}
      </header>

      <section className="space-y-2">
        <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
          Correlation
        </h2>
        <div className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={ticket.candidate_id ? "info" : "neutral"}>
              {(ticket.correlation_outcome ?? "uncorrelated").replace(/_/g, " ")}
            </Badge>
            {ticket.candidate_id ? (
              <Link
                href={`/incidents/candidates/${ticket.candidate_id}`}
                className="font-mono text-xs underline underline-offset-2"
              >
                {ticket.candidate_id}
              </Link>
            ) : (
              <span className="text-xs text-neutral-500">candidate: none</span>
            )}
            {ticket.correlation_score !== null && (
              <span className="text-xs text-neutral-500">
                score {ticket.correlation_score}
              </span>
            )}
            {ticket.correlation_version && (
              <span className="text-xs text-neutral-500">
                {ticket.correlation_version}
              </span>
            )}
          </div>
          {ticket.correlation_reason && (
            <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
              {ticket.correlation_reason}
            </p>
          )}
          <p className="mt-2 text-xs text-neutral-500">
            Recorded when the ticket arrived. A later change to thresholds does not
            rewrite it.
          </p>
        </div>

        {openReviews.map((review) => (
          <CorrelationReviewCard key={review.id} review={review} />
        ))}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
          Triage
        </h2>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Predicted {serviceLabel(names, ticket.service_id)} ·{" "}
          {ticket.priority ?? "unclassified"} · {ticket.issue_type ?? "unclassified"}
          {ticket.reported_service_id && (
            <>
              {" "}
              · reporter stated {serviceLabel(names, ticket.reported_service_id)}
            </>
          )}
        </p>
        {triage.ok ? (
          <TriagePanel result={triage.data} serviceNames={names} />
        ) : (
          <p className="text-sm text-neutral-500">
            Triage signals unavailable: {triage.error}
          </p>
        )}
      </section>
    </div>
  );
}

function BackLink() {
  return (
    <p className="text-sm">
      <Link className="underline underline-offset-2" href="/tickets">
        ← All tickets
      </Link>
    </p>
  );
}
