/**
 * Caveats, shown next to the numbers they qualify.
 *
 * An evaluation page where every metric is green and unqualified is a marketing page.
 * These are the things that would materially change how a reader should read a score,
 * and they belong beside the score rather than in a footnote nobody opens.
 */
export function Caveats({ items }: { items: { title: string; detail: string }[] }) {
  return (
    <div className="rounded border border-amber-300 p-3 dark:border-amber-900">
      <p className="text-xs font-medium tracking-wide text-amber-800 uppercase dark:text-amber-500">
        Read with these caveats
      </p>
      <ul className="mt-2 space-y-1.5 text-sm">
        {items.map((item) => (
          <li key={item.title}>
            <span className="font-medium">{item.title}.</span>{" "}
            <span className="text-neutral-600 dark:text-neutral-400">{item.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The Polaris correlation result, reported as text.
 *
 * Unlike everything else on this page these figures are not read from a committed
 * artifact: the run is over the Polaris corpus, which is CC BY-SA and deliberately not
 * redistributed, so its report stays in gitignored `data/processed/evals/`. The numbers
 * are transcribed here with their provenance stated rather than quietly omitted, because
 * the external result is less flattering than the authored one and worth showing.
 */
export function PolarisFinding() {
  return (
    <div className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-sm font-semibold">
          The same comparison on 23,994 external tickets
        </h3>
        <span className="text-xs text-neutral-500">
          Polaris corpus · run offline · artifact not committed
        </span>
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-neutral-500">
            <tr>
              <th className="py-1 pr-4 font-medium">Metric</th>
              <th className="py-1 pr-4 font-medium">deterministic</th>
              <th className="py-1 pr-4 font-medium">semantic</th>
              <th className="py-1 font-medium">Change</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-neutral-200 dark:border-neutral-800">
              <td className="py-1 pr-4">True pairs recovered</td>
              <td className="py-1 pr-4 tabular-nums">1,187</td>
              <td className="py-1 pr-4 tabular-nums">1,393</td>
              <td className="py-1 tabular-nums text-green-700 dark:text-green-500">
                +17.4%
              </td>
            </tr>
            <tr className="border-t border-neutral-200 dark:border-neutral-800">
              <td className="py-1 pr-4">Pairwise precision</td>
              <td className="py-1 pr-4 tabular-nums">78.98%</td>
              <td className="py-1 pr-4 tabular-nums">79.74%</td>
              <td className="py-1 text-neutral-500 tabular-nums">+0.8pp — flat</td>
            </tr>
            <tr className="border-t border-neutral-200 dark:border-neutral-800">
              <td className="py-1 pr-4">
                False-merge rate{" "}
                <span className="text-xs text-neutral-500">(lower is better)</span>
              </td>
              <td className="py-1 pr-4 tabular-nums">31.06%</td>
              <td className="py-1 pr-4 tabular-nums">32.08%</td>
              <td className="py-1 tabular-nums text-amber-700 dark:text-amber-500">
                +1.0pp — worse
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-sm text-neutral-600 dark:text-neutral-400">
        Embeddings recover materially more true pairs at roughly unchanged precision, and
        invent slightly more incidents that are not happening. On the authored set above,
        every delta was exactly zero — the two versions grouped identically. The external
        corpus is where the difference shows, and it is a trade rather than a win.
      </p>
      <p className="mt-2 text-xs text-neutral-500">
        Absolute recall is ~0.2% on this corpus for both versions: its ground-truth events
        are large and our thresholds are tuned to avoid false merges. That number measures
        the corpus and our threshold choice, not a capability ceiling.
      </p>
    </div>
  );
}
