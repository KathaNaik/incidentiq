import { Badge } from "@/components/badge";
import type { PolicyReplayReport } from "@/lib/api";

/**
 * Policy quality, kept separate from model quality on purpose.
 *
 * These are the same investigator-v2 recommendations scored by two different policies,
 * so the only variable is the gate. Reading them next to the investigator's own metrics
 * is the point: a model that recommends nothing scores a perfect unsafe-action rate, and
 * a policy that blocks everything scores the same way.
 */
export function PolicyComparison({ report }: { report: PolicyReplayReport }) {
  const rows: { key: string; label: string; lowerIsBetter?: boolean }[] = [
    { key: "unsafe_action_allowed_rate", label: "Unsafe action allowed", lowerIsBetter: true },
    { key: "valid_action_blocked_rate", label: "Valid action blocked", lowerIsBetter: true },
    { key: "policy_eligible_remediation_recall", label: "Policy-eligible recall" },
    { key: "policy_eligible_remediation_precision", label: "Policy-eligible precision" },
  ];

  const v1 = report.versions.find((v) => v.policy_version === "action-policy-v1");
  const v2 = report.versions.find((v) => v.policy_version === "action-policy-v2");
  if (!v1 || !v2) return null;

  const pct = (value: number | null) =>
    value === null ? "n/a" : `${(value * 100).toFixed(1)}%`;

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-base font-semibold">Policy: generic versus action-specific</h2>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          The same {v2.recommendations} recorded investigator-v2 recommendations, scored by
          two policies. <span className="font-medium">action-policy-v1</span> asked one
          question of every action — are there two independent kinds of evidence?{" "}
          <span className="font-medium">action-policy-v2</span> asks each action its own,
          because evidence that a service is failing is not evidence that a particular
          action fixes it.
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Badge>{report.eval_version}</Badge>
          <Badge tone="info">{report.investigator_version}</Badge>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-neutral-500">
            <tr>
              <th className="py-1 pr-4 font-medium">Metric</th>
              <th className="py-1 pr-4 font-medium">policy-v1</th>
              <th className="py-1 font-medium">policy-v2</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.key}
                className="border-t border-neutral-200 dark:border-neutral-800"
              >
                <td className="py-1 pr-4">
                  {row.label}
                  {row.lowerIsBetter && (
                    <span className="text-xs text-neutral-500"> (lower is better)</span>
                  )}
                </td>
                <td className="py-1 pr-4 tabular-nums">{pct(v1.metrics[row.key] ?? null)}</td>
                <td className="py-1 tabular-nums">{pct(v2.metrics[row.key] ?? null)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded border border-neutral-300 p-4 text-sm dark:border-neutral-700">
        <p className="font-medium">
          On this held-out run the two policies score identically — and that is the finding.
        </p>
        <p className="mt-1 text-neutral-600 dark:text-neutral-400">
          Every restart investigator-v2 recommended landed on a service whose error
          signature genuinely indicates a stalled worker, which is the one mechanism a
          restart addresses. Action-specific policy does not block them, because on that
          evidence a restart is the right kind of action. What was wrong in those cases was
          the model concluding at all, not the action it chose — a diagnosis failure, which
          policy is not the place to fix.
        </p>
        <p className="mt-2 text-neutral-600 dark:text-neutral-400">
          Where v2 does separate from v1 is the authored matrix, on cases this run did not
          happen to contain: a restart proposed against a configuration or credential
          failure, against a healthy service, or where a recent release is the better
          explanation. v1 allowed all of those.
        </p>
      </div>

      <p className="text-xs text-neutral-500">{report.note}</p>
    </section>
  );
}
