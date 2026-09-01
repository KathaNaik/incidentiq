import Link from "next/link";

/**
 * The five-minute path through the product.
 *
 * The workflow only makes sense end to end, and a visitor has no way to discover the
 * order — the pages look like independent tables. This names the sequence and links each
 * step to the page that performs it.
 *
 * Steps report their own state from real data rather than being ticked off by a wizard.
 * That keeps it honest: "2 waiting" appears because two reviews exist, and if an operator
 * clears them the step says so. Nothing here drives the workflow or fakes progress.
 */
export function GuidedTour({
  pendingReviews,
  awaitingApproval,
  executed,
  hasIncident,
  firstIncidentId,
}: {
  pendingReviews: number;
  awaitingApproval: number;
  executed: number;
  hasIncident: boolean;
  firstIncidentId: string | null;
}) {
  const steps = [
    {
      title: "Submit a report",
      body: "File one the way a support tool would. Watch it get classified and either join an incident or stand alone.",
      href: "/tickets",
      cta: "Go to reports",
      state: null,
    },
    {
      title: "Resolve an ambiguous one",
      body: "When correlation cannot decide, it asks instead of guessing. You answer: same incident, or not.",
      href: "/reviews",
      cta: "Open review queue",
      state: pendingReviews > 0 ? `${pendingReviews} waiting` : "none waiting",
    },
    {
      title: "Investigate an incident",
      body: "Open one and press Run investigation. It takes about twelve seconds and cites every piece of evidence it used.",
      href: firstIncidentId ? `/incidents/candidates/${firstIncidentId}` : "/incidents",
      cta: hasIncident ? "Open an incident" : "See incidents",
      state: null,
    },
    {
      title: "Approve and run a fix",
      body: "Rules decide whether the recommendation is even proposable. You decide whether it executes — and the execution is simulated.",
      href: firstIncidentId ? `/incidents/candidates/${firstIncidentId}` : "/incidents",
      cta: "Continue on the incident",
      state:
        awaitingApproval > 0
          ? `${awaitingApproval} awaiting you`
          : executed > 0
            ? `${executed} executed`
            : null,
    },
  ];

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
          Try it
        </h2>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          The whole workflow, in four steps and about five minutes.
        </p>
      </div>

      <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {steps.map((step, index) => (
          <li
            key={step.title}
            className="flex flex-col rounded border border-neutral-300 p-3 dark:border-neutral-700"
          >
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-xs text-neutral-400 tabular-nums dark:text-neutral-600">
                {index + 1}
              </span>
              <span className="text-sm font-medium">{step.title}</span>
            </div>
            <p className="mt-1 flex-1 text-sm text-neutral-600 dark:text-neutral-400">
              {step.body}
            </p>
            {step.state && (
              <p className="mt-2 text-xs text-neutral-500">{step.state}</p>
            )}
            <Link
              href={step.href}
              className="mt-2 text-sm underline underline-offset-2"
            >
              {step.cta}
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
