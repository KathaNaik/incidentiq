import Link from "next/link";

import { ApiError } from "@/components/api-error";
import { Badge } from "@/components/badge";
import { CandidateCard } from "@/components/candidate-card";
import {
  load,
  fetchCandidates,
  fetchIncidents,
  fetchServices,
  type CorrelationMode,
} from "@/lib/api";
import {
  formatTimestamp,
  incidentSeverityLabel,
  incidentStatusLabel,
  serviceLabel,
  serviceNames,
} from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function IncidentsPage({
  searchParams,
}: PageProps<"/incidents">) {
  const params = await searchParams;
  const mode: CorrelationMode = params.mode === "semantic" ? "semantic" : "deterministic";

  const result = await load(async () => {
    const [incidents, services, correlation] = await Promise.all([
      fetchIncidents(),
      fetchServices(),
      fetchCandidates(mode),
    ]);
    return { incidents, services, correlation };
  });

  if (!result.ok) {
    return (
      <div className="space-y-6">
        <Header />
        <ApiError error={result.error} />
      </div>
    );
  }

  const { incidents, services, correlation } = result.data;
  const names = serviceNames(services);

  return (
    <div className="space-y-8">
      <Header />

      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
            Potential incidents — {mode} correlation baseline
          </h2>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Groupings proposed from the ticket stream using time, service, issue type and
            shared identifiers
            {mode === "semantic"
              ? ", plus embedding similarity. The embedding is one signal among five — it cannot merge across a service conflict or a time gap on its own."
              : " — rules only, no model."}{" "}
            Nothing here is an incident until a person says so.{" "}
            <span className="text-neutral-500">
              {correlation.candidates.length} candidates from {correlation.ticket_count}{" "}
              tickets · {correlation.version}
            </span>
          </p>
          <div className="mt-2 flex gap-2 text-sm">
            {(["deterministic", "semantic"] as const).map((option) => (
              <Link
                key={option}
                href={option === "deterministic" ? "/incidents" : "/incidents?mode=semantic"}
                className={`rounded border px-2 py-1 text-xs ${
                  mode === option
                    ? "border-neutral-500 font-medium"
                    : "border-neutral-300 text-neutral-600 dark:border-neutral-700 dark:text-neutral-400"
                }`}
              >
                {option}
              </Link>
            ))}
          </div>
        </div>
        {correlation.candidates.length === 0 ? (
          <p className="rounded border border-dashed border-neutral-300 p-4 text-sm text-neutral-600 dark:border-neutral-700 dark:text-neutral-400">
            No candidates. The baseline found no group of tickets with enough shared
            evidence — leaving them separate is the intended answer, not a failure.
          </p>
        ) : (
          <ul className="space-y-3">
            {correlation.candidates.map((candidate) => (
              <CandidateCard
                key={candidate.id}
                candidate={candidate}
                serviceNames={names}
                mode={mode}
              />
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
          Declared incidents
        </h2>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Hand-declared in the fixture data. Correlation does not read these, so the
          candidates above are what the baseline found on its own.
        </p>
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
      </section>
    </div>
  );
}

function Header() {
  return (
    <header className="space-y-1">
      <h1 className="text-xl font-semibold">Incidents</h1>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Candidate groupings proposed by the correlation baseline, and the incidents
        already declared in the fixture data.
      </p>
    </header>
  );
}
