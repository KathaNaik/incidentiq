import { Badge } from "@/components/badge";
import type { TriagePrediction, TriageResult } from "@/lib/api";
import { ticketPriorityLabel } from "@/lib/format";

/**
 * Shows what the rule-based baseline concluded and, more importantly, why. It is
 * labelled as a keyword baseline everywhere it appears: no model is involved, and the
 * UI should not imply otherwise.
 */
export function TriagePanel({
  result,
  serviceNames,
}: {
  result: TriageResult;
  serviceNames: Map<string, string>;
}) {
  const label = (prediction: TriagePrediction, kind: string) => {
    if (prediction.value === null) {
      return prediction.status === "ambiguous" ? "Ambiguous" : "Not determined";
    }
    if (kind === "service") return serviceNames.get(prediction.value) ?? prediction.value;
    if (kind === "priority")
      return ticketPriorityLabel(
        prediction.value as "low" | "medium" | "high" | "critical",
      );
    return prediction.value.replace(/_/g, " ");
  };

  const rows: { kind: string; heading: string; prediction: TriagePrediction }[] = [
    { kind: "service", heading: "Service", prediction: result.service },
    { kind: "issue_type", heading: "Issue type", prediction: result.issue_type },
    { kind: "priority", heading: "Priority", prediction: result.priority },
  ];

  return (
    <section className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
      <header className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-medium">Deterministic triage baseline</h2>
        <code className="text-xs text-neutral-500">{result.version}</code>
        <p className="w-full text-sm text-neutral-600 dark:text-neutral-400">
          Keyword and phrase rules only — no model. Every number below comes from a rule
          in <code>rules.py</code>.
        </p>
      </header>

      <dl className="mt-4 space-y-3">
        {rows.map((row) => (
          <div key={row.kind}>
            <div className="flex flex-wrap items-center gap-2">
              <dt className="w-24 text-sm text-neutral-600 dark:text-neutral-400">
                {row.heading}
              </dt>
              <dd className="flex flex-wrap items-center gap-2">
                <Badge
                  tone={row.prediction.value === null ? "neutral" : "info"}
                >
                  {label(row.prediction, row.kind)}
                </Badge>
                <span className="text-xs text-neutral-500">
                  score {row.prediction.score} · {row.prediction.status}
                </span>
              </dd>
            </div>
            <p className="mt-1 ml-24 pl-2 text-xs text-neutral-600 dark:text-neutral-400">
              {row.prediction.explanation}
            </p>
          </div>
        ))}
      </dl>

      <div className="mt-4">
        <h3 className="text-xs font-medium tracking-wide text-neutral-500 uppercase">
          Matched signals ({result.signals.length})
        </h3>
        {result.signals.length === 0 ? (
          <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
            No rule matched this text.
          </p>
        ) : (
          <ul className="mt-2 space-y-1 text-xs">
            {result.signals.map((signal, index) => (
              <li key={`${signal.target}-${signal.matched_text}-${index}`}>
                <code>{signal.matched_text}</code>{" "}
                <span className="text-neutral-500">
                  {signal.signal_type} · {signal.weight > 0 ? "+" : ""}
                  {signal.weight} · {signal.source_field} → {signal.target}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
