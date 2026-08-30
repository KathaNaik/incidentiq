import { Badge } from "@/components/badge";
import type { EmbeddingBakeoff } from "@/lib/api";

/**
 * The embedding bake-off, reported as an ordering problem.
 *
 * The headline is **separation margin** — the weakest true paraphrase minus the strongest
 * pair that must never merge. Negative means no threshold separates them, and threshold
 * tuning cannot help however much of it you do.
 *
 * Absolute cosine is shown but deliberately not ranked on: a model that scores everything
 * higher has learned nothing about incident identity, and reading the columns left to
 * right makes that visible rather than burying it under an aggregate.
 */
export function EmbeddingBakeoff({ report }: { report: EmbeddingBakeoff }) {
  const separable = report.models.filter((m) => m.separable);

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-base font-semibold">Embedding model bake-off</h2>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          One question: does a model rank genuine same-incident paraphrases above pairs
          that must never merge? Same pair set, same embedding text, same everything
          except the model.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-neutral-500">
            <tr>
              <th className="py-1 pr-4 font-medium">Model</th>
              <th className="py-1 pr-4 font-medium">Dim</th>
              <th className="py-1 pr-4 font-medium">True paraphrase</th>
              <th className="py-1 pr-4 font-medium">Must-not-merge</th>
              <th className="py-1 pr-4 font-medium">Separation</th>
              <th className="py-1 font-medium">Ordering</th>
            </tr>
          </thead>
          <tbody>
            {report.models.map((model) => (
              <tr
                key={model.model_id}
                className="border-t border-neutral-200 dark:border-neutral-800"
              >
                <td className="py-1 pr-4">
                  {model.model_id}
                  <span className="block text-xs text-neutral-500">
                    {model.size_gb} GB
                  </span>
                </td>
                <td className="py-1 pr-4 tabular-nums">{model.dimension}</td>
                <td className="py-1 pr-4 tabular-nums">
                  {model.positive_min?.toFixed(3)} – {model.positive_max?.toFixed(3)}
                </td>
                <td className="py-1 pr-4 tabular-nums">
                  {model.dangerous_min?.toFixed(3)} – {model.dangerous_max?.toFixed(3)}
                </td>
                <td
                  className={`py-1 pr-4 tabular-nums ${
                    model.separable
                      ? "text-green-700 dark:text-green-500"
                      : "text-amber-700 dark:text-amber-500"
                  }`}
                >
                  {model.separation_margin > 0 ? "+" : ""}
                  {model.separation_margin.toFixed(4)}
                </td>
                <td className="py-1 tabular-nums">
                  {((model.ordering_accuracy ?? 0) * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded border border-amber-300 p-3 text-sm dark:border-amber-900">
        <p className="font-medium">
          {separable.length === 0
            ? "No model tested separates the two."
            : `${separable.length} of ${report.models.length} models separate the two.`}
        </p>
        <p className="mt-1 text-neutral-600 dark:text-neutral-400">
          Every separation margin above is negative: in each model the strongest
          must-not-merge pair scores <em>higher</em> than the weakest genuine paraphrase.
          Ordering accuracy near 50% is a coin flip. A model eighteen times the baseline&apos;s
          size and one from an entirely different family fail the same way, so this is a
          property of generic cosine similarity on this task rather than of one model.
        </p>
        <p className="mt-2 text-neutral-600 dark:text-neutral-400">
          Near-duplicates score ~0.99 in every model and are excluded from the margin —
          they already attach deterministically, and counting them would make each model
          look separable while the cases that need help stayed unrecovered.
        </p>
      </div>

      <div className="flex flex-wrap gap-2 text-xs text-neutral-500">
        {Object.entries(report.unsupported).map(([name, why]) => (
          <span key={name}>
            <Badge>not tested</Badge> {name}: {why}
          </span>
        ))}
      </div>
    </section>
  );
}
