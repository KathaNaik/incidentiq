import { Badge } from "@/components/badge";
import type { RetrievalResult } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";

const PROVENANCE_LABELS: Record<string, string> = {
  "northstar-authored": "Northstar — authored",
  "itsm-mit": "External corpus (MIT)",
};

/**
 * Past incidents that resemble this one. Every heading here says *historical* on
 * purpose: these are resolved cases with the causes they turned out to have, not a
 * claim about what is happening now. Nothing in this milestone reasons about the
 * current incident, and the UI must not imply otherwise.
 */
export function SimilarIncidents({ result }: { result: RetrievalResult }) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
          Similar historical incidents
        </h2>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          Resolved incidents whose reported symptoms resemble this candidate, retrieved
          from {result.corpus_size} past cases by embedding similarity. The causes and
          fixes below are what <em>those</em> incidents turned out to be — IncidentIQ is
          not claiming any of them explains this one.
        </p>
      </div>

      {!result.strong_match && (
        <p className="rounded border border-amber-300 p-3 text-sm text-amber-900 dark:border-amber-900 dark:text-amber-200">
          No close precedent. The best match scored below the threshold for a confident
          one, so treat these as loosely related at most.
        </p>
      )}

      <ul className="space-y-3">
        {result.hits.map((hit) => (
          <li
            key={hit.incident.id}
            className="rounded border border-neutral-300 p-4 dark:border-neutral-700"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={hit.rank === 1 ? "info" : "neutral"}>
                {hit.score.toFixed(3)}
              </Badge>
              <span className="font-medium">{hit.incident.title}</span>
              <span className="font-mono text-xs text-neutral-500">
                {hit.incident.id}
              </span>
              <Badge>{PROVENANCE_LABELS[hit.incident.provenance]}</Badge>
              {hit.incident.occurred_at && (
                <span className="text-xs text-neutral-500">
                  {formatTimestamp(hit.incident.occurred_at)}
                </span>
              )}
            </div>

            <p className="mt-2 text-sm text-neutral-700 dark:text-neutral-300">
              {hit.incident.summary}
            </p>

            {(hit.incident.services.length > 0 ||
              hit.incident.observed_errors.length > 0) && (
              <div className="mt-2 flex flex-wrap gap-1">
                {hit.incident.services.map((service) => (
                  <Badge key={service}>{service}</Badge>
                ))}
                {hit.incident.observed_errors.map((error) => (
                  <Badge key={error} tone="warn">
                    {error}
                  </Badge>
                ))}
              </div>
            )}

            <dl className="mt-3 space-y-2 text-sm">
              <div>
                <dt className="text-xs font-medium tracking-wide text-neutral-500 uppercase">
                  Root cause (of that incident)
                </dt>
                <dd className="mt-1 text-neutral-700 dark:text-neutral-300">
                  {hit.incident.outcome.root_cause}
                </dd>
              </div>
              {hit.incident.outcome.resolution_steps.length > 0 && (
                <div>
                  <dt className="text-xs font-medium tracking-wide text-neutral-500 uppercase">
                    How it was resolved
                  </dt>
                  <dd className="mt-1">
                    <ol className="list-decimal space-y-1 pl-5 text-neutral-700 dark:text-neutral-300">
                      {hit.incident.outcome.resolution_steps.map((step) => (
                        <li key={step}>{step}</li>
                      ))}
                    </ol>
                  </dd>
                </div>
              )}
            </dl>

            <ul className="mt-3 space-y-0.5 text-xs text-neutral-500">
              {hit.signals.map((signal) => (
                <li key={signal.kind}>
                  <code>
                    {signal.kind} +{signal.contribution.toFixed(3)}
                  </code>{" "}
                  {signal.detail}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>

      <p className="text-xs text-neutral-500">
        Retrieved by {result.version} using {result.provider}.
      </p>
    </section>
  );
}
