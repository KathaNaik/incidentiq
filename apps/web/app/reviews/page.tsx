import Link from "next/link";

import { ApiError } from "@/components/api-error";
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
          Two reports can describe one outage in words that share almost nothing —{" "}
          <em>&ldquo;invalid assertion after redirect&rdquo;</em> and{" "}
          <em>&ldquo;stuck at the login screen&rdquo;</em>. Correlation refuses to guess on
          those, because a false merge sends people chasing a problem that is not
          happening. So it asks.
        </p>
        <p className="text-xs text-neutral-500">
          Each decision is pinned to the exact candidate snapshot shown. If that candidate
          changes first, the review refreshes rather than applying your answer to a
          different grouping. Decisions are recorded against a fixed demo operator — this
          prototype has no authentication.
        </p>
      </header>

      <section className="space-y-4">
        <h2 className="text-base font-semibold">
          Waiting{pending.ok ? ` · ${pending.data.length}` : ""}
        </h2>

        {!pending.ok && <ApiError error={pending.error} />}

        {pending.ok && pending.data.length === 0 && (
          <div className="rounded border border-dashed border-neutral-300 p-6 dark:border-neutral-700">
            <p className="text-sm font-medium">Nothing to review</p>
            <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
              Every report so far was either clear enough to place automatically or clearly
              unrelated. Both are finished answers, not a backlog.
            </p>
            <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
              To see this queue work, submit a report on the{" "}
              <Link className="underline underline-offset-2" href="/tickets">
                reports page
              </Link>{" "}
              that describes an existing incident in different words — say{" "}
              <em>&ldquo;people sign in and then just wait on a blank screen&rdquo;</em>.
            </p>
          </div>
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
          Why the answers are kept: three attempts to recover these cases automatically
          failed, and the last one showed why — the training labels came from a dataset
          answering a different question. Operator decisions answer the runtime&rsquo;s own
          question, so they are exported as training data
          (<code>scripts/export_correlation_labels.py</code>). No model is retrained
          automatically, and the sample is deliberately not random: reviews exist only
          where automation declined, so the base rate carries no information about
          correlation in general.
        </p>
      </footer>
    </div>
  );
}
