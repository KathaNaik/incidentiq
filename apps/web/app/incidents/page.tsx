import { ApiError } from "@/components/api-error";
import { Badge } from "@/components/badge";
import { load, fetchIncidents, fetchServices } from "@/lib/api";
import {
  formatTimestamp,
  incidentSeverityLabel,
  incidentStatusLabel,
  serviceLabel,
  serviceNames,
} from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function IncidentsPage() {
  const result = await load(async () => {
    const [incidents, services] = await Promise.all([
      fetchIncidents(),
      fetchServices(),
    ]);
    return { incidents, services };
  });

  if (!result.ok) {
    return (
      <div className="space-y-6">
        <Header />
        <ApiError error={result.error} />
      </div>
    );
  }

  const { incidents, services } = result.data;
  const names = serviceNames(services);

  return (
    <div className="space-y-6">
      <Header />
      <ul className="space-y-3">
        {incidents.map((incident) => (
          <li
            key={incident.id}
            className="rounded border border-neutral-300 p-4 dark:border-neutral-700"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={incident.severity === "sev1" ? "danger" : "warn"}>
                {incidentSeverityLabel(incident.severity)}
              </Badge>
              <Badge tone="info">{incidentStatusLabel(incident.status)}</Badge>
              <span className="font-mono text-xs text-neutral-500">{incident.id}</span>
              <span className="font-medium">{incident.title}</span>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {incident.affected_service_ids.map((serviceId) => (
                <Badge key={serviceId}>{serviceLabel(names, serviceId)}</Badge>
              ))}
              <span className="text-xs text-neutral-500">
                {incident.ticket_count} linked{" "}
                {incident.ticket_count === 1 ? "ticket" : "tickets"} · detected{" "}
                {formatTimestamp(incident.detected_at)}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Header() {
  return (
    <header className="space-y-1">
      <h1 className="text-xl font-semibold">Incidents</h1>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Most recently detected first. Ticket links are declared in the fixture data —
        correlation is not implemented yet.
      </p>
    </header>
  );
}
