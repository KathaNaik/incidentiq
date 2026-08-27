import { Badge } from "@/components/badge";
import type { SliceExample, VersionComparison } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";

const METRIC_LABELS: Record<string, string> = {
  pairwise_precision: "Pairwise precision",
  pairwise_recall: "Pairwise recall",
  pairwise_f1: "Pairwise F1",
  false_merge_rate: "False-merge rate",
  singleton_accuracy: "Left-alone accuracy",
  event_recovery_rate: "Event recovery",
};

// Metrics where a smaller number is the better outcome.
const LOWER_IS_BETTER = new Set(["false_merge_rate"]);

const SLICE_LABELS: Record<string, { title: string; description: string }> = {
  semantic_win: {
    title: "Semantic wins",
    description:
      "A true pair the rules missed because the wording barely overlapped, recovered by the embedding.",
  },
  semantic_false_merge: {
    title: "Semantic false merges",
    description:
      "Pairs the embedding pulled together that belong to different incidents.",
  },
  semantic_regression: {
    title: "Semantic regressions",
    description:
      "True pairs the rules found and the semantic version lost, because weight moved off lexical overlap.",
  },
  time_guardrail: {
    title: "Time guardrail saves",
    description:
      "The embedding rated these highly similar; the time decay kept them apart.",
  },
  conflict_guardrail: {
    title: "Conflict guardrail saves",
    description:
      "The embedding rated these highly similar; a service or issue-type conflict kept them apart.",
  },
};

export function VersionComparisonSection({
  comparison,
}: {
  comparison: VersionComparison;
}) {
  const byKind = new Map<string, SliceExample[]>();
  for (const example of comparison.slices) {
    byKind.set(example.kind, [...(byKind.get(example.kind) ?? []), example]);
  }

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold">
          Correlation: baseline versus semantic
        </h2>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Both versions ran on the same tickets with the same labels, thresholds and
          candidate generation. Only the signal set differs, so the deltas below are
          attributable to the embedding.
        </p>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Badge>{comparison.baseline_version}</Badge>
          <span className="text-xs text-neutral-500">vs</span>
          <Badge tone="info">{comparison.candidate_version}</Badge>
          <span className="text-xs text-neutral-500">
            {comparison.ticket_count} tickets · generated{" "}
            {formatTimestamp(comparison.generated_at)}
          </span>
        </div>
        <ul className="pt-1 text-sm text-neutral-600 dark:text-neutral-400">
          {comparison.notes.map((note) => (
            <li key={note}>— {note}</li>
          ))}
        </ul>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-neutral-500">
            <tr>
              <th className="py-1 pr-4 font-medium">Metric</th>
              <th className="py-1 pr-4 font-medium">Deterministic</th>
              <th className="py-1 pr-4 font-medium">Semantic</th>
              <th className="py-1 font-medium">Delta</th>
            </tr>
          </thead>
          <tbody>
            {comparison.metrics.map((metric) => {
              const better = LOWER_IS_BETTER.has(metric.name)
                ? metric.delta < 0
                : metric.delta > 0;
              const tone =
                metric.delta === 0
                  ? "text-neutral-500"
                  : better
                    ? "text-green-700 dark:text-green-500"
                    : "text-amber-700 dark:text-amber-500";
              return (
                <tr
                  key={metric.name}
                  className="border-t border-neutral-200 dark:border-neutral-800"
                >
                  <td className="py-1 pr-4">
                    {METRIC_LABELS[metric.name] ?? metric.name}
                    {LOWER_IS_BETTER.has(metric.name) && (
                      <span className="text-xs text-neutral-500"> (lower is better)</span>
                    )}
                  </td>
                  <td className="py-1 pr-4 tabular-nums">
                    {(metric.baseline * 100).toFixed(1)}%
                  </td>
                  <td className="py-1 pr-4 tabular-nums">
                    {(metric.candidate * 100).toFixed(1)}%
                  </td>
                  <td className={`py-1 tabular-nums ${tone}`}>
                    {metric.delta > 0 ? "+" : ""}
                    {(metric.delta * 100).toFixed(1)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {[...byKind.entries()].map(([kind, examples]) => (
        <div key={kind} className="space-y-2">
          <h3 className="text-xs font-medium tracking-wide text-neutral-500 uppercase">
            {SLICE_LABELS[kind]?.title ?? kind} ({examples.length})
          </h3>
          {SLICE_LABELS[kind] && (
            <p className="text-sm text-neutral-600 dark:text-neutral-400">
              {SLICE_LABELS[kind].description}
            </p>
          )}
          <ul className="space-y-3">
            {examples.map((example) => (
              <li
                key={`${example.ticket_a}-${example.ticket_b}`}
                className="rounded border border-neutral-300 p-4 dark:border-neutral-700"
              >
                <p className="font-mono text-xs text-neutral-500">
                  {example.ticket_a} · {example.ticket_b}
                </p>
                {example.text && (
                  <p className="mt-2 text-sm whitespace-pre-line text-neutral-700 dark:text-neutral-300">
                    {example.text}
                  </p>
                )}
                <p className="mt-2 text-xs text-neutral-600 dark:text-neutral-400">
                  {example.explanation}
                </p>
                <ul className="mt-2 space-y-0.5 text-xs text-neutral-500">
                  {example.signals.map((signal) => (
                    <li key={signal}>
                      <code>{signal}</code>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
