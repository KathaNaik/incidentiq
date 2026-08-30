import { Badge } from "@/components/badge";
import type { TicketIntakeResult } from "@/lib/api";

/**
 * How correlation reached its answer, when hybrid was the strategy.
 *
 * Renders nothing for a single-strategy decision — there was no fallback stage, and
 * showing an empty one would suggest a fallback was considered and declined.
 *
 * The interesting line is usually the one saying an embedding was *not* computed.
 * Hybrid's claim is about how rarely semantic work is needed, and the reason it was
 * skipped is the evidence for that claim.
 */
export function CorrelationPath({
  correlation,
}: {
  correlation: TicketIntakeResult["correlation"];
}) {
  const fallback = correlation.fallback_stage;
  const deterministic = correlation.deterministic_stage;
  if (!correlation.strategy || !fallback || !deterministic) return null;

  const blocking = fallback.decisions.flatMap((d) => d.blocking_reasons);
  const eligible = fallback.decisions.filter((d) => d.eligible);

  return (
    <div className="mt-2 rounded border border-neutral-300 p-3 text-sm dark:border-neutral-700">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs tracking-wide text-neutral-500 uppercase">
          Correlation path
        </span>
        <Badge>{correlation.strategy}</Badge>
      </div>

      <p className="mt-2">
        <span className="text-xs tracking-wide text-neutral-500 uppercase">
          Deterministic stage
        </span>
        <br />
        {deterministic.attached ? (
          <>
            Attached at score {deterministic.score} — no embedding computed.
          </>
        ) : (
          <>No attachment.</>
        )}
      </p>

      <p className="mt-2">
        <span className="text-xs tracking-wide text-neutral-500 uppercase">
          Semantic fallback
        </span>
        <br />
        {fallback.failed ? (
          <span className="text-amber-700 dark:text-amber-500">
            Failed — the ticket is stored and remains uncorrelated. No score was
            substituted.
          </span>
        ) : fallback.semantic_invoked ? (
          <>
            Ran
            {fallback.semantic_score !== null && (
              <> · similarity-weighted score {fallback.semantic_score}</>
            )}
            {correlation.embedding_model && (
              <span className="text-xs text-neutral-500"> · {correlation.embedding_model}</span>
            )}
          </>
        ) : (
          <>Not triggered — no embedding was computed.</>
        )}
      </p>

      {(blocking.length > 0 || eligible.length > 0) && (
        <ul className="mt-2 space-y-0.5 text-xs text-neutral-600 dark:text-neutral-400">
          {eligible.flatMap((d) =>
            d.reasons.map((reason) => (
              <li key={`${d.candidate_id}-${reason}`}>
                <span className="text-green-700 dark:text-green-500">✓</span> {reason}
              </li>
            )),
          )}
          {blocking.map((reason) => (
            <li key={reason}>
              <span className="text-neutral-500">✗</span> {reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
