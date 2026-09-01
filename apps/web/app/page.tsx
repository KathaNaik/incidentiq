import Link from "next/link";

import { ApiError } from "@/components/api-error";
import { ApiStatus } from "@/components/api-status";
import { Badge } from "@/components/badge";
import { DemoReset } from "@/components/demo-reset";
import { GuidedTour } from "@/components/guided-tour";
import { HowItWorks } from "@/components/how-it-works";
import { IncidentQueue } from "@/components/incident-queue";
import {
  load,
  fetchActions,
  fetchCorrelationReviews,
  fetchIncidents,
  fetchRuntimeCandidates,
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
    const [incidents, tickets, services, candidates] = await Promise.all([
      fetchIncidents(),
      fetchTickets(),
      fetchServices(),
      // Durable state, not a recomputation. See fetchRuntimeCandidates.
      fetchRuntimeCandidates(),
    ]);
    return { incidents, tickets, services, candidates };
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

  const { incidents, tickets, services, candidates } = result.data;
  const rows = actions.ok ? actions.data : [];
  const pendingReviews = reviews.ok ? reviews.data : [];

  const activeIncidents = incidents.filter((i) => i.status !== "resolved");
  const openTickets = tickets.filter((t) => t.status !== "resolved");
  const awaitingApproval = rows.filter((a) => a.status === "awaiting_approval");
  const executed = rows.filter(
    (a) => a.status === "succeeded" || a.status === "failed",
  );

  // Built from counts already fetched. Nothing here costs an extra request.
  const attention = [
    pendingReviews.length > 0 && {
      text: `${pendingReviews.length} report${pendingReviews.length === 1 ? "" : "s"} need a correlation decision`,
      href: "/reviews",
      cta: "Review",
    },
    awaitingApproval.length > 0 && {
      text: `${awaitingApproval.length} proposed fix${awaitingApproval.length === 1 ? "" : "es"} awaiting approval`,
      href: "/incidents",
      cta: "Open incidents",
    },
  ].filter(Boolean) as { text: string; href: string; cta: string }[];

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <Header />
        <ApiStatus />
      </div>

      {/* Metrics first: the question a dashboard answers is "what needs attention", and
          that is a row of numbers, not a paragraph. */}
      <section className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Needs review"
          value={pendingReviews.length}
          hint="correlation undecided"
          tone={pendingReviews.length > 0 ? "warn" : "neutral"}
          href="/reviews"
        />
        <StatTile
          label="Awaiting approval"
          value={awaitingApproval.length}
          hint="blocked on a human"
          tone={awaitingApproval.length > 0 ? "warn" : "neutral"}
        />
        <StatTile label="Open reports" value={openTickets.length} />
        <StatTile
          label="Proposed incidents"
          value={candidates.length}
          hint="grouped by correlation"
        />
      </section>

      {attention.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
            Needs attention
          </h2>
          <ul className="divide-y divide-neutral-200 rounded border border-amber-400 dark:divide-neutral-800 dark:border-amber-800">
            {attention.map((item) => (
              <li key={item.text} className="flex flex-wrap items-center gap-2 p-3">
                <span className="text-sm">{item.text}</span>
                <Link
                  href={item.href}
                  className="ml-auto text-sm underline underline-offset-2"
                >
                  {item.cta}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <IncidentQueue
        candidates={candidates}
        version={candidates[0]?.correlation_version ?? "deterministic-correlation-v2"}
        services={serviceNames(services)}
        actions={rows}
      />

      <GuidedTour
        pendingReviews={pendingReviews.length}
        awaitingApproval={awaitingApproval.length}
        executed={executed.length}
        hasIncident={candidates.length > 0}
        firstIncidentId={candidates[0]?.id ?? null}
      />

      <HowItWorks />

      {activeIncidents.length > 0 && (
        <section className="space-y-3">
          <div>
            <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
              Pre-loaded demo incidents
            </h2>
            <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
              Authored by hand so the demo starts with history. These were not produced by
              correlation — the queue above is what the system worked out for itself.
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
        Scattered reports, grouped into incidents, investigated against evidence, and
        gated behind a human before anything runs. Every number on this page is counted
        from real records — nothing here is a placeholder.
      </p>
    </header>
  );
}
