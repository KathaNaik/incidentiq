import { Badge } from "@/components/badge";
import type { EvalReport } from "@/lib/api";

const ROWS: { name: string; label: string; lowerIsBetter?: boolean }[] = [
  { name: "remediation_recall", label: "Remediation recall" },
  { name: "policy_eligible_remediation_recall", label: "Policy-eligible remediation recall" },
  { name: "remediation_precision", label: "Remediation precision" },
  { name: "unsupported_remediation_rate", label: "Unsupported remediation rate", lowerIsBetter: true },
  { name: "leading_hypothesis_accuracy", label: "Leading-hypothesis accuracy" },
  { name: "abstention_accuracy", label: "Abstention accuracy" },
  { name: "unsupported_citation_rate", label: "Unsupported citation rate", lowerIsBetter: true },
  { name: "structured_output_validity", label: "Structured-output validity" },
];

/**
 * The v1 → v2 experiment, as an experiment.
 *
 * v1 recommended nothing, which made its 0% unsupported-remediation rate look like
 * discipline. The comparison exists so both halves of the trade are visible at once:
 * recall bought at some cost in precision is the finding, not a headline score.
 */
export function InvestigatorComparison({ v1, v2 }: { v1: EvalReport; v2: EvalReport }) {
  const byName = (report: EvalReport, name: string) =>
    report.metrics.find((metric) => metric.name === name) ?? null;

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-base font-semibold">Investigator: v1 versus v2</h2>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          Same held-out cases, same model and settings, one prompt change. v1 withheld
          remediation almost entirely; v2 separates &ldquo;is there a diagnosis?&rdquo;
          from &ldquo;is there a supported action?&rdquo; and tells the model its
          recommendation is reviewed by policy and a human rather than executed.
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <Badge>{v1.version}</Badge>
          <span className="text-xs text-neutral-500">vs</span>
          <Badge tone="info">{v2.version}</Badge>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-neutral-500">
            <tr>
              <th className="py-1 pr-4 font-medium">Metric</th>
              <th className="py-1 pr-4 font-medium">v1</th>
              <th className="py-1 pr-4 font-medium">v2</th>
              <th className="py-1 font-medium">Delta</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => {
              const a = byName(v1, row.name);
              const b = byName(v2, row.name);
              if (!a || !b) return null;
              const delta = b.accuracy - a.accuracy;
              const better = row.lowerIsBetter ? delta < 0 : delta > 0;
              const tone =
                delta === 0
                  ? "text-neutral-500"
                  : better
                    ? "text-green-700 dark:text-green-500"
                    : "text-amber-700 dark:text-amber-500";
              return (
                <tr key={row.name} className="border-t border-neutral-200 dark:border-neutral-800">
                  <td className="py-1 pr-4">
                    {row.label}
                    {row.lowerIsBetter && (
                      <span className="text-xs text-neutral-500"> (lower is better)</span>
                    )}
                  </td>
                  <td className="py-1 pr-4 tabular-nums">{(a.accuracy * 100).toFixed(1)}%</td>
                  <td className="py-1 pr-4 tabular-nums">{(b.accuracy * 100).toFixed(1)}%</td>
                  <td className={`py-1 tabular-nums ${tone}`}>
                    {delta > 0 ? "+" : ""}
                    {(delta * 100).toFixed(1)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Read the recall and precision rows together. v1&apos;s perfect unsupported-remediation
        rate came from recommending nothing at all; v2 recommends on every case where an
        action was justified, and pays for it with some recommendations the evidence did
        not warrant. The deterministic policy layer is what decides which of those reach
        a human.
      </p>
    </section>
  );
}
