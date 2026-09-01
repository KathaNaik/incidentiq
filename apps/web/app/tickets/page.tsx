import Link from "next/link";

import { ApiError } from "@/components/api-error";
import { Badge } from "@/components/badge";
import { Disclosure } from "@/components/disclosure";
import { TicketIntakeForm } from "@/components/ticket-intake-form";
import {
  load,
  fetchCorrelationReviews,
  fetchRuntimeTickets,
  fetchServices,
} from "@/lib/api";
import { formatTimestamp, serviceLabel, serviceNames } from "@/lib/format";

export const dynamic = "force-dynamic";

const OUTCOME_TONE: Record<string, "neutral" | "info" | "warn" | "danger"> = {
  attached: "info",
  created_candidate: "info",
  uncorrelated: "neutral",
  ambiguous: "warn",
  failed: "danger",
};

/**
 * The ticket queue, as an operator reads it.
 *
 * Every row is a persisted runtime ticket with what the system decided about it: the
 * deterministic triage prediction, and whether correlation put it on an incident.
 * "Uncorrelated" is shown as a normal state rather than a gap — a report that matches
 * nothing is a real answer, and hiding it would misrepresent what correlation does.
 */
export default async function TicketsPage() {
  const result = await load(async () => {
    const [tickets, services] = await Promise.all([
      fetchRuntimeTickets(),
      fetchServices(),
    ]);
    return { tickets, services };
  });

  // Loaded separately so an unreachable review queue degrades to "no pending reviews"
  // rather than blanking the ticket list.
  const reviews = await load(() => fetchCorrelationReviews(true));
  const awaitingReview = new Set(
    reviews.ok ? reviews.data.map((review) => review.ticket_id) : [],
  );

  if (!result.ok) {
    return (
      <div className="space-y-6">
        <Header />
        <ApiError error={result.error} />
      </div>
    );
  }

  const { tickets, services } = result.data;
  const names = serviceNames(services);
  const uncorrelated = tickets.filter((ticket) => ticket.candidate_id === null);

  return (
    <div className="space-y-8">
      <Header />

      {/* The queue is what an operator came for; submitting is what a reviewer trying the
          demo came for. Collapsed keeps both reachable without either dominating. */}
      <Disclosure summary="Submit a report" hint="try the intake API">
        <TicketIntakeForm
          services={services.map((service) => ({ id: service.id, name: service.name }))}
        />
      </Disclosure>

      <section className="space-y-3">
        <div className="flex flex-wrap items-baseline gap-2">
          <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
            Tickets
          </h2>
          <span className="text-xs text-neutral-500">
            {tickets.length} total · {uncorrelated.length} uncorrelated
          </span>
        </div>

        {tickets.length === 0 ? (
          <div className="rounded border border-dashed border-neutral-300 p-6 text-center dark:border-neutral-700">
            <p className="text-sm font-medium">No tickets yet</p>
            <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
              Submit one above, or seed the authored Northstar set with{" "}
              <code>uv run python scripts/seed_tickets.py</code>.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded border border-neutral-300 dark:border-neutral-700">
            <table className="w-full text-sm">
              <thead className="border-b border-neutral-300 text-left text-xs text-neutral-500 dark:border-neutral-700">
                <tr>
                  <th className="px-3 py-2 font-medium">Observed</th>
                  <th className="px-3 py-2 font-medium">Report</th>
                  <th className="px-3 py-2 font-medium">Triage</th>
                  <th className="px-3 py-2 font-medium">Correlation</th>
                  <th className="px-3 py-2 font-medium">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
                {tickets.map((ticket) => (
                  <tr key={ticket.id} className="align-top">
                    <td className="px-3 py-2 text-xs whitespace-nowrap text-neutral-500">
                      {formatTimestamp(ticket.created_at)}
                      {ticket.received_at.slice(0, 16) !==
                        ticket.created_at.slice(0, 16) && (
                        <span className="block text-neutral-400 dark:text-neutral-600">
                          received {formatTimestamp(ticket.received_at)}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <Link
                        href={`/tickets/${ticket.id}`}
                        className="font-medium underline underline-offset-2"
                      >
                        {ticket.title}
                      </Link>
                      <span className="block font-mono text-xs text-neutral-500">
                        {ticket.external_id ?? ticket.id}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-neutral-600 dark:text-neutral-400">
                      {serviceLabel(names, ticket.service_id)}
                      <span className="block text-xs">
                        {[ticket.priority, ticket.issue_type]
                          .filter(Boolean)
                          .join(" · ") || "unclassified"}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {ticket.candidate_id ? (
                        <Link
                          href={`/incidents/candidates/${ticket.candidate_id}`}
                          className="underline underline-offset-2"
                        >
                          <Badge tone="info">attached</Badge>{" "}
                          <span className="font-mono text-xs">{ticket.candidate_id}</span>
                        </Link>
                      ) : awaitingReview.has(ticket.id) ? (
                        <Link href="/reviews" className="underline underline-offset-2">
                          <Badge tone="warn">needs review</Badge>
                          <span className="block text-xs text-neutral-500">
                            waiting on an operator
                          </span>
                        </Link>
                      ) : (
                        <>
                          <Badge
                            tone={
                              OUTCOME_TONE[ticket.correlation_outcome ?? "uncorrelated"]
                            }
                          >
                            {(ticket.correlation_outcome ?? "uncorrelated").replace(
                              /_/g,
                              " ",
                            )}
                          </Badge>
                          <span className="block text-xs text-neutral-500">
                            candidate: none
                          </span>
                        </>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-neutral-500">
                      {ticket.source}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function Header() {
  return (
    <header className="space-y-1">
      <h1 className="text-xl font-semibold">Tickets</h1>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Reports as they arrive. Each is triaged deterministically and compared against the
        incidents still open — no language model is involved in either step.
      </p>
    </header>
  );
}
