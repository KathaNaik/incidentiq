import { Badge } from "@/components/badge";
import type { EvidenceItem } from "@/lib/api";

/**
 * Derived chronology, shown as fact rather than as conclusion.
 *
 * These are not observations — nobody saw them — they are relationships the application
 * computed from the timestamps on the observations above. Kept in their own section for
 * that reason, and phrased as ordering rather than causation.
 *
 * The distinction the wording holds to: a change that preceded a failure *may* have
 * caused it; a change that followed one cannot have started it. The first is a lead, the
 * second is dispositive, and neither is a verdict. Verdicts live in the AI hypothesis
 * section, clearly labelled as the model's opinion.
 */
export function TemporalEvidence({ evidence }: { evidence: EvidenceItem[] }) {
  const temporal = evidence.filter((item) => item.kind === "temporal");
  if (temporal.length === 0) return null;

  const onset = temporal.find((item) => item.id.startsWith("temporal:onset:"));
  const attributions = temporal.filter((item) =>
    item.id.startsWith("temporal:attribution:"),
  );
  const relationships = temporal.filter(
    (item) =>
      !item.id.startsWith("temporal:onset:") &&
      !item.id.startsWith("temporal:attribution:"),
  );

  return (
    <details className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
      <summary className="cursor-pointer text-sm font-medium">
        Temporal evidence ({temporal.length})
      </summary>
      <p className="mt-2 text-xs text-neutral-500">
        Computed by IncidentIQ from the timestamps above — not observed, and not a claim
        about cause. Ordering is necessary evidence for causality and never proof of it.
      </p>

      {onset && (
        <p className="mt-3 text-sm">
          <span className="text-xs tracking-wide text-neutral-500 uppercase">
            Incident onset
          </span>
          <br />
          {onset.summary}
        </p>
      )}

      {attributions.length > 0 && (
        <div className="mt-3">
          <p className="text-xs tracking-wide text-neutral-500 uppercase">
            Deployment attribution
          </p>
          <ul className="mt-1 space-y-1 text-sm">
            {attributions.map((item) => {
              const plausible = item.attributes?.temporally_plausible === "true";
              return (
                <li key={item.id}>
                  <span
                    className={
                      plausible
                        ? "text-amber-700 dark:text-amber-500"
                        : "text-neutral-500"
                    }
                  >
                    {plausible ? "✓" : "✗"}
                  </span>{" "}
                  {item.summary}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {relationships.length > 0 && (
        <div className="mt-3">
          <p className="text-xs tracking-wide text-neutral-500 uppercase">Ordering</p>
          <ul className="mt-1 space-y-1 text-sm">
            {relationships.map((item) => {
              const compatibility = item.attributes?.compatibility;
              const tone =
                compatibility === "temporally_compatible"
                  ? "text-amber-700 dark:text-amber-500"
                  : compatibility === "temporally_incompatible"
                    ? "text-neutral-500"
                    : "text-neutral-400";
              return (
                <li key={item.id}>
                  <span className={tone}>
                    {compatibility === "temporally_incompatible" ? "✗" : "·"}
                  </span>{" "}
                  {item.summary}
                  {compatibility && compatibility !== "not_applicable" && (
                    <Badge>{compatibility.replace(/_/g, " ")}</Badge>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </details>
  );
}
