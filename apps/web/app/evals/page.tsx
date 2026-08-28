import { ApiError } from "@/components/api-error";
import { EvalReportSection } from "@/components/eval-report";
import { VersionComparisonSection } from "@/components/version-comparison";
import {
  load,
  fetchCorrelationComparison,
  fetchCorrelationEvaluation,
  fetchInvestigationEvaluation,
  fetchRetrievalEvaluation,
  fetchTriageEvaluation,
  type EvalReport,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function EvalsPage() {
  const [triage, correlation, comparison, retrieval, investigation] =
    await Promise.all([
      load(fetchTriageEvaluation),
      load(() => fetchCorrelationEvaluation("deterministic")),
      load(fetchCorrelationComparison),
      load(fetchRetrievalEvaluation),
      load(fetchInvestigationEvaluation),
    ]);

  return (
    <div className="space-y-10">
      <Header />

      <Suite
        title="Triage baseline"
        description="Service, issue type and priority predicted from ticket text by phrase rules."
        result={triage}
      />

      <Suite
        title="Correlation baseline"
        description="Tickets grouped into candidate incidents by time, service, issue type, weighted word overlap and shared identifiers. Precision is preferred over recall: a false merge invents an incident that is not happening."
        result={correlation}
      />

      {comparison.ok && <VersionComparisonSection comparison={comparison.data} />}

      <Suite
        title="AI investigation"
        description="Ranked root-cause hypotheses over typed evidence, graded programmatically: did it cite the decisive evidence, did it abstain when it should have, did it ever cite evidence that was never supplied, did it recommend an action the evidence did not justify. Lower is better for the two 'unsupported' rates."
        result={investigation}
      />

      <Suite
        title="Historical retrieval"
        description="Given a current incident, how often does a past incident with the same root cause appear in the top K? Leave-one-out over the external corpus, where relevance means same root-cause family. Read the caveat below the metrics: that corpus is clusters of near-duplicates, so these numbers measure the pipeline more than the capability."
        result={retrieval}
      />
    </div>
  );
}

function Suite({
  title,
  description,
  result,
}: {
  title: string;
  description: string;
  result: { ok: true; data: EvalReport } | { ok: false; error: string };
}) {
  if (!result.ok) {
    return (
      <section className="space-y-3">
        <h2 className="text-base font-semibold">{title}</h2>
        <ApiError error={result.error} />
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          If the API is running, the artifact may not have been generated yet — run the
          matching <code>scripts/evaluate_*.py --suite golden</code> in{" "}
          <code>apps/api</code>.
        </p>
      </section>
    );
  }

  return (
    <EvalReportSection title={title} description={description} report={result.data} />
  );
}

function Header() {
  return (
    <header className="space-y-1">
      <h1 className="text-xl font-semibold">Evals</h1>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Measured results for the deterministic baselines, read from the artifacts the
        offline harness produced. Nothing on this page is hard-coded. The external
        benchmark runs offline — its report is derived from a licensed corpus and stays
        out of the repository.
      </p>
    </header>
  );
}
