import { ApiError } from "@/components/api-error";
import { Badge } from "@/components/badge";
import { load, fetchTriageEvaluation, type EvalMetric } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";

export const dynamic = "force-dynamic";

const METRIC_LABELS: Record<string, string> = {
  service: "Service accuracy",
  issue_type: "Issue-type accuracy",
  priority: "Priority accuracy",
};

export default async function EvalsPage() {
  const result = await load(fetchTriageEvaluation);

  if (!result.ok) {
    return (
      <div className="space-y-6">
        <Header />
        <ApiError error={result.error} />
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          If the API is running, the evaluation artifact may not have been generated yet:
          run <code>uv run python scripts/evaluate_triage.py --suite golden</code> in{" "}
          <code>apps/api</code>.
        </p>
      </div>
    );
  }

  const report = result.data;

  return (
    <div className="space-y-8">
      <Header />

      <section className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="info">{report.version}</Badge>
          <span className="text-sm">
            {report.suite} suite · {report.case_count} cases
          </span>
          <span className="text-xs text-neutral-500">
            generated {formatTimestamp(report.generated_at)}
          </span>
        </div>
        <ul className="text-sm text-neutral-600 dark:text-neutral-400">
          {report.notes.map((note) => (
            <li key={note}>— {note}</li>
          ))}
        </ul>
      </section>

      <section className="grid gap-3 sm:grid-cols-3">
        {report.metrics.map((metric) => (
          <MetricTile key={metric.name} metric={metric} />
        ))}
      </section>

      {report.confusion.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
            Errors by category
          </h2>
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
        </section>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-medium tracking-wide text-neutral-500 uppercase">
          Failures ({report.failures.length})
        </h2>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Each failure shows what the rules matched, so the reason for the miss is
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
                <p className="mt-2 text-sm text-neutral-700 dark:text-neutral-300">
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
      </section>
    </div>
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
      </p>
      <p className="mt-1 text-xs text-neutral-500">
        {metric.correct}/{metric.total} correct · {metric.abstained} abstained
        {metric.majority_baseline !== null &&
          ` · majority baseline ${(metric.majority_baseline * 100).toFixed(1)}%`}
      </p>
    </div>
  );
}

function Header() {
  return (
    <header className="space-y-1">
      <h1 className="text-xl font-semibold">Evals</h1>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Measured results for the deterministic triage baseline, read from the artifact
        the offline harness produced. Nothing on this page is hard-coded.
      </p>
    </header>
  );
}
