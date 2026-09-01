/**
 * Where a claim came from, as a badge instead of a paragraph.
 *
 * The safety story of this product is that different kinds of statement carry different
 * authority: a timestamp the system read is not the same thing as a model's hypothesis,
 * and neither is the same as a rule that gates an action. That distinction was previously
 * carried by a sentence under every heading — "no model was involved in this decision",
 * "observed evidence and model hypothesis are kept visually separate" — which made the
 * product read as though it were continuously defending itself.
 *
 * The distinction is the same. It is now stated once, in a consistent place, in two
 * words.
 *
 * Deliberately a small closed set. A badge vocabulary only works while a reader can hold
 * all of it, and these five are the ones that change how much a statement should be
 * trusted. Status — needs review, stale, current — stays on the plain `Badge`, because it
 * describes *state* rather than provenance.
 */
export type Provenance =
  | "observed"
  | "derived"
  | "ai"
  | "rules"
  | "human"
  | "simulated";

const LABELS: Record<Provenance, string> = {
  observed: "Observed",
  derived: "Derived",
  ai: "AI inference",
  rules: "Rules only",
  human: "Human decision",
  simulated: "Simulated",
};

/** One line, available near the badge, for a reader who has not met it before. */
export const MEANINGS: Record<Provenance, string> = {
  observed: "Read directly from a record. Not interpreted.",
  derived: "Computed from observed records by arithmetic, not judgement.",
  ai: "A language model's hypothesis. It must cite evidence by id, and every citation is validated before it appears here.",
  rules: "Deterministic application logic. No model runs here.",
  human: "An operator decided this, and the decision is attributed and audited.",
  simulated: "Nothing was contacted. The outcome is recorded, no infrastructure changed.",
};

const TONES: Record<Provenance, string> = {
  observed:
    "border-neutral-400 text-neutral-700 dark:border-neutral-600 dark:text-neutral-300",
  derived:
    "border-neutral-400 text-neutral-700 dark:border-neutral-600 dark:text-neutral-300",
  ai: "border-violet-400 text-violet-800 dark:border-violet-800 dark:text-violet-300",
  rules: "border-blue-400 text-blue-800 dark:border-blue-800 dark:text-blue-300",
  human: "border-emerald-500 text-emerald-800 dark:border-emerald-800 dark:text-emerald-300",
  simulated:
    "border-amber-400 text-amber-900 dark:border-amber-800 dark:text-amber-300",
};

export function ProvenanceBadge({ kind }: { kind: Provenance }) {
  return (
    <span
      className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase ${TONES[kind]}`}
    >
      {LABELS[kind]}
    </span>
  );
}

/**
 * The whole vocabulary in one place, for the page that introduces it.
 *
 * Rendered as real text rather than tooltips: what separates an observation from a
 * hypothesis is exactly the information somebody needs to decide safely, and that must
 * not depend on hovering.
 */
export function ProvenanceKey({ kinds }: { kinds: Provenance[] }) {
  return (
    <dl className="grid gap-2 sm:grid-cols-2">
      {kinds.map((kind) => (
        <div key={kind} className="flex gap-2">
          <dt className="shrink-0">
            <ProvenanceBadge kind={kind} />
          </dt>
          <dd className="text-sm text-neutral-600 dark:text-neutral-400">
            {MEANINGS[kind]}
          </dd>
        </div>
      ))}
    </dl>
  );
}
