import Link from "next/link";

import { ApiError } from "@/components/api-error";
import { ApiStatus } from "@/components/api-status";
import { Badge } from "@/components/badge";
import { load, fetchIncidents, fetchServices, fetchTickets } from "@/lib/api";
import {
  incidentSeverityLabel,
  incidentStatusLabel,
  formatTimestamp,
} from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const result = await load(async () => {
    const [incidents, tickets, services] = await Promise.all([
      fetchIncidents(),
      fetchTickets(),
      fetchServices(),
    ]);
    return { incidents, tickets, services };
  });

  if (!result.ok) {
    return (
      <div className="space-y-6">
        <Header />
        <ApiStatus />
        <ApiError error={result.error} />
      </div>
    );
  }

  const { incidents, tickets, services } = result.data;

  // Every number below is derived from what the API returned.
  const activeIncidents = incidents.filter(
    (incident) => incident.status !== "resolved",
  );
  const openTickets = tickets.filter((ticket) => ticket.status !== "resolved");
  const untriaged = tickets.filter(
    (ticket) => ticket.priority === null || ticket.service_id === null,
  );
  const linkedTicketCount = incidents.reduce(
    (total, incident) => total + incident.ticket_count,
    0,
  );

  return (
    <div className="space-y-8">
      <Header />
      <ApiStatus />

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatTile label="Active incidents" value={activeIncidents.length} />
        <StatTile label="Open tickets" value={openTickets.length} />
        <StatTile label="Untriaged tickets" value={untriaged.length} />
        <StatTile
          label="Tickets not linked to an incident"
          value={tickets.length - linkedTicketCount}
        />
        <StatTile label="Services" value={services.length} />
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
          Active incidents
        </h2>
        {activeIncidents.length === 0 ? (
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            No active incidents.
          </p>
        ) : (
          <ul className="space-y-2">
            {activeIncidents.map((incident) => (
              <li
                key={incident.id}
                className="rounded border border-neutral-300 p-4 dark:border-neutral-700"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={incident.severity === "sev1" ? "danger" : "warn"}>
                    {incidentSeverityLabel(incident.severity)}
                  </Badge>
                  <Badge tone="info">{incidentStatusLabel(incident.status)}</Badge>
                  <span className="font-medium">{incident.title}</span>
                </div>
                <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
                  {incident.id} · detected {formatTimestamp(incident.detected_at)} ·{" "}
                  {incident.ticket_count} linked{" "}
                  {incident.ticket_count === 1 ? "ticket" : "tickets"}
                </p>
              </li>
            ))}
          </ul>
        )}
        <p className="text-sm">
          <Link className="underline" href="/incidents">
            All incidents
          </Link>
        </p>
      </section>

      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Incident–ticket links in this dataset are declared by hand. Automatic correlation
        is not implemented yet, so nothing on this page is inferred.
      </p>
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">{label}</p>
    </div>
  );
}

function Header() {
  return (
    <header className="space-y-1">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Operational overview, counted from the records the API returns.
      </p>
    </header>
  );
}
