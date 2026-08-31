import Link from "next/link";

import { ApiError } from "@/components/api-error";
import { ApiStatus } from "@/components/api-status";
import { Badge } from "@/components/badge";
import { DemoReset } from "@/components/demo-reset";
import { IncidentQueue } from "@/components/incident-queue";
import {
  load,
  fetchActions,
  fetchCandidates,
  fetchCorrelationReviews,
  fetchIncidents,
  fetchServices,
  fetchTickets,
} from "@/lib/api";
import { formatTimestamp, serviceNames } from "@/lib/format";

export const dynamic = "force-dynamic";

/**
 * The operations dashboard.
 *
 * Every number here is counted from records the API returned. Nothing is a placeholder,
 * and there is no metric on this page that would still render if the backend went away —
 * a dashboard that shows plausible figures when it has no data is worse than one that
 * says it cannot reach the API.
 */
export default async function DashboardPage() {
  const result = await load(async () => {
    const [incidents, tickets, services, correlation] = await Promise.all([
      fetchIncidents(),
      fetchTickets(),
      fetchServices(),
      fetchCandidates("deterministic"),
    ]);
    return { incidents, tickets, services, correlation };
  });

  // Action state lives in process memory and is empty until somebody walks the workflow.
  // Its absence must not blank the page, so it loads separately.
  const actions = await load(fetchActions);

  // Reviews are a queue an operator is expected to clear, so the count belongs beside the
  // other things waiting on a person. Loaded separately for the same reason as actions:
  // an empty or unreachable review queue must not blank the dashboard.
  const reviews = await load(() => fetchCorrelationReviews(true));

  if (!result.ok) {
    return (
      <div className="space-y-6">
        <Header />
        <ApiStatus />
        <ApiError error={result.error} />
      </div>
    );
  }

  const { incidents, tickets, services, correlation } = result.data;
  const rows = actions.ok ? actions.data : [];
  const pendingReviews = reviews.ok ? reviews.data : [];

  const activeIncidents = incidents.filter((i) => i.status !== "resolved");
  const openTickets = tickets.filter((t) => t.status !== "resolved");
  const awaitingApproval = rows.filter((a) => a.status === "awaiting_approval");
  const executed = rows.filter(
    (a) => a.status === "succeeded" || a.status === "failed",
  );

  return (
    <div className="space-y-8">
      <Header />
      <ApiStatus />

      <section className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatTile label="Open tickets" value={openTickets.length} />
        <StatTile label="Active incidents" value={activeIncidents.length} />
        <StatTile
          label="Candidate incidents"
          value={correlation.candidates.length}
          hint="proposed by correlation"
        />
        <StatTile
          label="Awaiting approval"
          value={awaitingApproval.length}
          tone={awaitingApproval.length > 0 ? "warn" : "neutral"}
        />
        <StatTile
          label="Needs review"
          value={pendingReviews.length}
          hint="correlation undecided"
          tone={pendingReviews.length > 0 ? "warn" : "neutral"}
          href="/reviews"
        />
        <StatTile
          label="Executed this session"
          value={executed.length}
          hint="simulated"
        />
      </section>

      <IncidentQueue
        candidates={correlation.candidates}
        version={correlation.version}
        services={serviceNames(services)}
        actions={rows}
      />

      {activeIncidents.length > 0 && (
        <section className="space-y-3">
          <div>
            <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
              Declared incidents
            </h2>
            <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
              Incident–ticket links in the fixture set are declared by hand. The queue
              above is what correlation inferred.
            </p>
          </div>
          <ul className="divide-y divide-neutral-200 rounded border border-neutral-300 dark:divide-neutral-800 dark:border-neutral-700">
            {activeIncidents.map((incident) => (
              <li key={incident.id} className="flex flex-wrap items-center gap-2 p-3">
                <Badge tone={incident.severity === "sev1" ? "danger" : "warn"}>
                  {incident.severity.toUpperCase()}
                </Badge>
                <span className="text-sm font-medium">{incident.title}</span>
                <span className="ml-auto text-xs text-neutral-500">
                  {incident.ticket_count}{" "}
                  {incident.ticket_count === 1 ? "ticket" : "tickets"} · detected{" "}
                  {formatTimestamp(incident.detected_at)}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-sm">
            <Link className="underline underline-offset-2" href="/incidents">
              All incidents
            </Link>
          </p>
        </section>
      )}

      <DemoReset />
    </div>
  );
}

function StatTile({
  label,
  value,
  hint,
  tone = "neutral",
  href,
}: {
  label: string;
  value: number;
  hint?: string;
  tone?: "neutral" | "warn";
  /** Given when the count is a queue somebody is expected to go and clear. */
  href?: string;
}) {
  const className = `block rounded border p-4 ${
    tone === "warn"
      ? "border-amber-400 dark:border-amber-800"
      : "border-neutral-300 dark:border-neutral-700"
  }`;

  const body = (
    <>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">{label}</p>
      {hint && <p className="text-xs text-neutral-500">{hint}</p>}
    </>
  );

  if (href) {
    return (
      <Link
        href={href}
        className={`${className} hover:border-neutral-500 dark:hover:border-neutral-500`}
      >
        {body}
      </Link>
    );
  }

  return <div className={className}>{body}</div>;
}

function Header() {
  return (
    <header className="space-y-1">
      <h1 className="text-xl font-semibold">Operations</h1>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Fragmented tickets, correlated into candidate incidents, investigated against
        evidence, and gated behind deterministic policy and a human. Every count below is
        derived from records the API returned.
      </p>
    </header>
  );
}
