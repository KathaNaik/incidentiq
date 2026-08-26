import Link from "next/link";

import { ApiError } from "@/components/api-error";
import { Badge } from "@/components/badge";
import { TriagePanel } from "@/components/triage-panel";
import { load, fetchServices, fetchTicket, fetchTicketTriage } from "@/lib/api";
import {
  formatTimestamp,
  serviceLabel,
  serviceNames,
  ticketPriorityLabel,
  ticketStatusLabel,
} from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function TicketDetailPage({ params }: PageProps<"/tickets/[ticketId]">) {
  const { ticketId } = await params;

  const result = await load(async () => {
    const [ticket, triage, services] = await Promise.all([
      fetchTicket(ticketId),
      fetchTicketTriage(ticketId),
      fetchServices(),
    ]);
    return { ticket, triage, services };
  });

  if (!result.ok) {
    return (
      <div className="space-y-6">
        <BackLink />
        <ApiError error={result.error} />
      </div>
    );
  }

  const { ticket, triage, services } = result.data;
  const names = serviceNames(services);

  return (
    <div className="space-y-6">
      <BackLink />

      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-neutral-500">{ticket.id}</span>
          <h1 className="text-xl font-semibold">{ticket.title}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge>{ticketPriorityLabel(ticket.priority)}</Badge>
          <Badge>{ticketStatusLabel(ticket.status)}</Badge>
          <Badge>{serviceLabel(names, ticket.service_id)}</Badge>
          <span className="text-xs text-neutral-500">
            {ticket.reported_by} · {formatTimestamp(ticket.created_at)}
          </span>
        </div>
      </header>

      <section className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
        <h2 className="text-sm font-medium">Reported</h2>
        <p className="mt-2 text-sm whitespace-pre-line text-neutral-700 dark:text-neutral-300">
          {ticket.description}
        </p>
      </section>

      <TriagePanel result={triage} serviceNames={names} />

      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        The badges above are the values recorded on the ticket. The panel is what the
        baseline predicts from the text alone — it does not read them.
      </p>
    </div>
  );
}

function BackLink() {
  return (
    <p className="text-sm">
      <Link className="underline" href="/tickets">
        ← All tickets
      </Link>
    </p>
  );
}
