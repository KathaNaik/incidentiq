import { Badge } from "@/components/badge";
import type { EvalMetric, EvalReport } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";

const METRIC_LABELS: Record<string, string> = {
  service: "Service accuracy",
  issue_type: "Issue-type accuracy",
  priority: "Priority accuracy",
  pairwise_precision: "Pairwise precision",
  pairwise_recall: "Pairwise recall",
  pairwise_f1: "Pairwise F1",
  false_merge_rate: "False-merge rate",
  singleton_accuracy: "Left-alone accuracy",
  event_recovery_rate: "Event recovery",
};

// Lower is better for these, so the tile should not read as a score.
const INVERTED = new Set(["false_merge_rate"]);

export function EvalReportSection({
  title,
  description,
  report,
}: {
  title: string;
  description: string;
  report: EvalReport;
}) {
  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">{description}</p>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Badge tone="info">{report.version}</Badge>
          <span className="text-sm">
            {report.suite} suite · {report.case_count} cases
          </span>
          <span className="text-xs text-neutral-500">
            generated {formatTimestamp(report.generated_at)}
          </span>
        </div>
        <ul className="pt-1 text-sm text-neutral-600 dark:text-neutral-400">
          {report.notes.map((note) => (
            <li key={note}>— {note}</li>
          ))}
        </ul>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {report.metrics.map((metric) => (
          <MetricTile key={metric.name} metric={metric} />
        ))}
      </div>

      {report.confusion.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-medium tracking-wide text-neutral-500 uppercase">
            Errors by category
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-neutral-500">
                <tr>
                  <th className="py-1 pr-4 font-medium">Expected</th>
                  <th className="py-1 pr-4 font-medium">Predicted</th>
                  <th className="py-1 font-medium">Count</th>
                </tr>
              </thead>
              <tbody>
                {report.confusion.map((cell) => (
                  <tr
                    key={`${cell.expected}-${cell.predicted}`}
                    className="border-t border-neutral-200 dark:border-neutral-800"
                  >
                    <td className="py-1 pr-4 font-mono text-xs">{cell.expected}</td>
                    <td className="py-1 pr-4 font-mono text-xs">{cell.predicted}</td>
                    <td className="py-1 tabular-nums">{cell.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="space-y-2">
        <h3 className="text-xs font-medium tracking-wide text-neutral-500 uppercase">
          Failures ({report.failures.length})
        </h3>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Each failure carries the rules that fired, so the reason for the miss is
          visible rather than inferred.
        </p>
        <ul className="space-y-3">
          {report.failures.map((failure) => (
            <li
              key={`${failure.case_id}-${failure.metric}`}
              className="rounded border border-neutral-300 p-4 dark:border-neutral-700"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-neutral-500">
                  {failure.case_id}
                </span>
                <Badge>{failure.metric}</Badge>
                <span className="text-sm">
                  expected <code>{failure.expected ?? "—"}</code>, predicted{" "}
                  <code>{failure.predicted ?? "—"}</code>{" "}
                  <span className="text-neutral-500">({failure.status})</span>
                </span>
              </div>
              {failure.text && (
                <p className="mt-2 text-sm whitespace-pre-line text-neutral-700 dark:text-neutral-300">
                  {failure.text}
                </p>
              )}
              <p className="mt-2 text-xs text-neutral-600 dark:text-neutral-400">
                {failure.explanation}
              </p>
              {failure.signals.length > 0 && (
                <ul className="mt-2 space-y-0.5 text-xs text-neutral-500">
                  {failure.signals.map((signal) => (
                    <li key={signal}>
                      <code>{signal}</code>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function MetricTile({ metric }: { metric: EvalMetric }) {
  return (
    <div className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
      <p className="text-2xl font-semibold tabular-nums">
        {(metric.accuracy * 100).toFixed(1)}%
      </p>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        {METRIC_LABELS[metric.name] ?? metric.name}
        {INVERTED.has(metric.name) && (
          <span className="text-neutral-500"> (lower is better)</span>
        )}
      </p>
      <p className="mt-1 text-xs text-neutral-500">
        {metric.correct}/{metric.total}
        {metric.abstained > 0 && ` · ${metric.abstained} abstained`}
        {metric.majority_baseline !== null &&
          ` · majority baseline ${(metric.majority_baseline * 100).toFixed(1)}%`}
      </p>
    </div>
  );
}
