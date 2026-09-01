import { Badge } from "@/components/badge";

/**
 * What this is, and what to do with it.
 *
 * The dashboard previously opened with six numbers and three tables. That is the right
 * density for somebody who already knows the domain model and the wrong first impression
 * for everybody else — the interesting part of the product is a *sequence*, and a table
 * of current state does not reveal that a sequence exists.
 *
 * A native `<details>` rather than React state: it needs no JavaScript, it is keyboard
 * accessible and screen-reader labelled for free, and it cannot desynchronise between
 * server and client render. Collapsed by default and placed below the operational
 * content — the dashboard now opens with what needs attention, so this is reference for
 * a reader who wants it rather than a preamble everybody has to scroll past.
 */
export function HowItWorks() {
  return (
    <details className="rounded border border-neutral-300 dark:border-neutral-700">
      <summary className="flex cursor-pointer items-center gap-2 px-4 py-3 text-sm font-semibold">
        What is IncidentIQ?
        <Badge tone="info">Demo</Badge>
      </summary>

      <div className="space-y-4 border-t border-neutral-200 px-4 py-4 dark:border-neutral-800">
        <p className="text-sm text-neutral-700 dark:text-neutral-300">
          An incident rarely arrives as an incident. It arrives as a dozen separate reports
          from different people, each describing one symptom, mixed into a queue with
          everything else happening that morning. IncidentIQ groups those reports into one
          incident, works out what changed just before it started, and proposes a fix for a
          human to approve.
        </p>

        <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Step
            n={1}
            title="Reports arrive"
            body="Each is classified by rules — service, type, priority. No AI here."
          />
          <Step
            n={2}
            title="Correlation groups them"
            body="Time, service, shared identifiers and wording. Prefers missing a link to inventing one."
          />
          <Step
            n={3}
            title="AI investigates, once"
            body="Only when you ask. It must cite the evidence it was given, by id."
          />
          <Step
            n={4}
            title="A human approves"
            body="Rules decide whether a fix is proposable at all. You decide whether it runs."
          />
        </ol>

        <div className="rounded bg-neutral-50 p-3 dark:bg-neutral-900">
          <p className="text-sm font-medium">Nothing here touches real infrastructure.</p>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            The reports and services are invented for this demo, and remediation is
            simulated — approving a rollback records the decision and an audit trail, and
            contacts nothing. The only operation that calls a paid model is an
            investigation, and it never runs on its own.
          </p>
        </div>
      </div>
    </details>
  );
}

function Step({ n, title, body }: { n: number; title: string; body: string }) {
  return (
    <li className="rounded border border-neutral-200 p-3 dark:border-neutral-800">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-xs text-neutral-400 tabular-nums dark:text-neutral-600">
          {n}
        </span>
        <span className="text-sm font-medium">{title}</span>
      </div>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">{body}</p>
    </li>
  );
}
