import { ApiError } from "@/components/api-error";
import { Badge } from "@/components/badge";
import { load, fetchServices, fetchTickets, type TicketPriority } from "@/lib/api";
import {
  formatTimestamp,
  serviceLabel,
  serviceNames,
  ticketPriorityLabel,
  ticketStatusLabel,
} from "@/lib/format";

export const dynamic = "force-dynamic";

const PRIORITY_TONE = {
  critical: "danger",
  high: "warn",
  medium: "info",
  low: "neutral",
} as const satisfies Record<TicketPriority, string>;

export default async function TicketsPage() {
  const result = await load(async () => {
    const [tickets, services] = await Promise.all([fetchTickets(), fetchServices()]);
    return { tickets, services };
  });

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

  return (
    <div className="space-y-6">
      <Header count={tickets.length} />
      <ul className="space-y-3">
        {tickets.map((ticket) => (
          <li
            key={ticket.id}
            className="rounded border border-neutral-300 p-4 dark:border-neutral-700"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-neutral-500">{ticket.id}</span>
              <span className="font-medium">{ticket.title}</span>
            </div>
            <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
              {ticket.description}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Badge
                tone={
                  ticket.priority === null ? "neutral" : PRIORITY_TONE[ticket.priority]
                }
              >
                {ticketPriorityLabel(ticket.priority)}
              </Badge>
              <Badge>{ticketStatusLabel(ticket.status)}</Badge>
              <Badge>{serviceLabel(names, ticket.service_id)}</Badge>
              <span className="text-xs text-neutral-500">
                {ticket.reported_by} · {formatTimestamp(ticket.created_at)}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Header({ count }: { count?: number }) {
  return (
    <header className="space-y-1">
      <h1 className="text-xl font-semibold">Tickets</h1>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        {count === undefined
          ? "Incoming support tickets, newest first."
          : `${count} tickets, newest first. Priority and service are blank until a ticket is triaged.`}
      </p>
    </header>
  );
}
