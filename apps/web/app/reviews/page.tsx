import { ApiError } from "@/components/api-error";
import { Badge } from "@/components/badge";
import { CorrelationReviewCard } from "@/components/correlation-review";
import { fetchCorrelationReviews, load } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * The correlation review queue.
 *
 * This page exists because automatic correlation has a middle. Near-duplicates attach on
 * their own and clear conflicts are refused on their own; neither reaches an operator.
 * What lands here is the slice where the deterministic pass found a plausible candidate
 * and declined to commit — the decisions that are genuinely hard, and the only ones worth
 * a person's attention.
 *
 * Answering one does two things at once, and the page is honest about both: it fixes the
 * incident an operator is looking at now, and it records a label at exactly the boundary
 * the system keeps getting wrong.
 */
export default async function ReviewsPage() {
  const [pending, decided] = await Promise.all([
    load(() => fetchCorrelationReviews(true)),
    load(() => fetchCorrelationReviews(false)),
  ]);

  const history = decided.ok
    ? decided.data.filter((review) => review.status !== "pending")
    : [];

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-xl font-semibold">Correlation review</h1>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Reports that automatic correlation could not place. Each one asks a single
          question — is this the same incident? — against the candidate exactly as it
          stood when the question was raised.
        </p>
        <div className="flex flex-wrap gap-2">
          <Badge>review-policy-v1</Badge>
          <Badge tone="info">northstar-correlation-labels-v1</Badge>
        </div>
      </header>

      <section className="space-y-4">
        <h2 className="text-base font-semibold">
          Waiting{pending.ok ? ` · ${pending.data.length}` : ""}
        </h2>

        {!pending.ok && <ApiError error={pending.error} />}

        {pending.ok && pending.data.length === 0 && (
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            Nothing to review. Automatic correlation placed every report it has seen, or
            refused it outright — both are finished answers, not a backlog.
          </p>
        )}

        {pending.ok &&
          pending.data.map((review) => (
            <CorrelationReviewCard key={review.id} review={review} />
          ))}
      </section>

      {history.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold">Decided · {history.length}</h2>
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            Kept because each one is a label. The snapshot a decision was made against is
            stored with it, so a judgement stays readable after the incident has moved on.
          </p>
          {history.map((review) => (
            <CorrelationReviewCard key={review.id} review={review} />
          ))}
        </section>
      )}

      <footer className="border-t border-neutral-200 pt-4 dark:border-neutral-800">
        <p className="text-xs text-neutral-500">
          Decisions export as training data with{" "}
          <code>scripts/export_correlation_labels.py</code>. No model is retrained
          automatically, and the export is deliberately not a random sample — reviews
          exist only where automation declined, so the base rate here carries no
          information about correlation in general.
        </p>
      </footer>
    </div>
  );
}
