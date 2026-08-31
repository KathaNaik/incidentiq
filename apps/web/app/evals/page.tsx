import { ApiError } from "@/components/api-error";
import { Badge } from "@/components/badge";
import { Caveats, PolarisFinding } from "@/components/caveats";
import { EmbeddingBakeoff } from "@/components/embedding-bakeoff";
import { EvalReportSection } from "@/components/eval-report";
import { InvestigatorComparison } from "@/components/investigator-comparison";
import { PolicyComparison } from "@/components/policy-comparison";
import { VersionComparisonSection } from "@/components/version-comparison";
import {
  load,
  fetchCorrelationComparison,
  fetchCorrelationEvaluation,
  fetchEmbeddingBakeoff,
  fetchInvestigationEvaluation,
  fetchPolicyReplay,
  fetchPolicyEvaluation,
  fetchRetrievalEvaluation,
  fetchTriageEvaluation,
  type EvalReport,
} from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * The evaluation page, organised as the engineering progression rather than a scoreboard.
 *
 * Two things it deliberately does not do. It does not present every metric as green —
 * the caveats sit beside the numbers they qualify, because a saturated benchmark and a
 * real result look identical once you strip the context off. And it keeps *model
 * quality* and *system safety* in separate groups, since a model that recommends nothing
 * and a policy that blocks everything both score perfectly on the other's terms.
 */
export default async function EvalsPage() {
  const [
    triage,
    correlation,
    comparison,
    retrieval,
    investigationV1,
    policy,
    investigationV2,
    policyReplay,
    bakeoff,
  ] = await Promise.all([
    load(fetchTriageEvaluation),
    load(() => fetchCorrelationEvaluation("deterministic")),
    load(fetchCorrelationComparison),
    load(fetchRetrievalEvaluation),
    load(() => fetchInvestigationEvaluation("v1")),
    load(fetchPolicyEvaluation),
    load(() => fetchInvestigationEvaluation("v2")),
    load(fetchPolicyReplay),
    load(fetchEmbeddingBakeoff),
  ]);

  return (
    <div className="space-y-12">
      <Header />

      <Group
        step={1}
        title="Triage"
        lead="Service, issue type and priority predicted from ticket text by phrase rules. Deterministic — no model, no embeddings."
      >
        <Suite
          title="Triage baseline"
          description="Every prediction carries the signals that produced it, and the classifier abstains rather than guessing when nothing matches."
          result={triage}
        />
      </Group>

      <Group
        step={2}
        title="Correlation"
        lead="Tickets grouped into candidate incidents by time, service, issue type, weighted word overlap and shared identifiers. Precision is preferred over recall: a false merge invents an incident that is not happening."
      >
        <Suite
          title="Deterministic baseline"
          description="The authored Northstar correlation set."
          result={correlation}
        />
        {comparison.ok && <VersionComparisonSection comparison={comparison.data} />}
        <PolarisFinding />
        {bakeoff.ok && <EmbeddingBakeoff report={bakeoff.data} />}
      </Group>

      <Group
        step={3}
        title="Correlation safety — reconciliation"
        lead="A defect operator review exposed, and the versioned fix for it. No weight or threshold changed; only which question membership overlap is allowed to answer."
      >
        <Caveats
          items={[
            {
              title: "v1 let identity reconciliation imply membership",
              detail:
                "Intake maps each recomputed cluster onto a durable candidate by membership overlap, then assigned every cluster member to it. A ticket that clustered with one member inherited the whole incident: measured at 0.405 and 0.458 against the members it actually joined, against a 0.60 threshold. Operator review made it reachable, because confirming a low-overlap paraphrase is a reliable way to make durable membership diverge from what the stateless engine recomputes.",
            },
            {
              title: "deterministic-correlation-v2 fixes it without retuning",
              detail:
                "An arriving ticket must clear the engine's own attachment rule against the candidate's automatically established members. Judging against full membership was ruled out by measurement, not preference: a genuine later report scored 0.5366 against the widened membership and would have been refused. Against the automatic core the unrelated ticket still scores 0.4054 and the genuine one 0.6256.",
            },
            {
              title: "The authored online set could not have caught it",
              detail:
                "That suite runs the correlation engine over a seed plus an arriving ticket with no database and no durable candidate, so it never exercises reconciliation at all. v1 and v2 score identically on it by construction. That is a statement about the set's coverage, not evidence that v2 is safe — the PostgreSQL suites are what cover it.",
            },
            {
              title: "The residual cost is one operator decision",
              detail:
                "A refused ticket stays standalone in the active window, where the engine can still cluster it with a confirmed paraphrase. A later genuine report then lands within the ambiguity margin of two groupings and is called ambiguous rather than attached. It fails toward human review, never toward a false merge, and ambiguous reports now raise a review rather than sitting unseen.",
            },
          ]}
        />
      </Group>

      <Group
        step={4}
        title="Historical retrieval"
        lead="Given a current incident, how often does a past incident with the same root cause appear in the top K? Leave-one-out over the external corpus, where relevance means same root-cause family."
      >
        <Suite
          title="Retrieval baseline"
          description="Matching is on symptoms only. A historical cause is displayed after a match, never used to make one."
          result={retrieval}
        />
        <Caveats
          items={[
            {
              title: "This benchmark is unusually easy",
              detail:
                "The external corpus contains families of near-paraphrases, so a query's own family is highly separable from everything else. The scores measure that the retrieval pipeline works end to end; they overstate how well it would find genuinely differently-worded precedent.",
            },
          ]}
        />
      </Group>

      <Group
        step={5}
        title="Investigation — model quality"
        lead="What the model produced, scored against authored labels. This group measures the model alone: whether the system would have let any of it happen is the next group's question."
      >
        {investigationV1.ok && investigationV2.ok && (
          <InvestigatorComparison v1={investigationV1.data} v2={investigationV2.data} />
        )}
        <Suite
          title="investigator-v1 detail"
          description="Ranked root-cause hypotheses over typed evidence, graded programmatically: did it cite the decisive evidence, did it abstain when it should have, did it ever cite evidence that was never supplied, did it recommend an action the evidence did not justify. Lower is better for the two 'unsupported' rates."
          result={investigationV1}
        />
        <Caveats
          items={[
            {
              title: "Abstention varies between runs",
              detail:
                "v1 scored 75% on one run and 68.8% on another with an unchanged prompt. Single-run abstention differences smaller than about seven points are not readable, and no claim here rests on one.",
            },
            {
              title: "v2 bought recall with unsupported recommendations",
              detail:
                "Remediation recall went 0% → 100%, and raw unsupported remediation went 0% → 18.8%. v1's perfect unsupported rate came from recommending nothing at all. Read the two together or neither means anything.",
            },
            {
              title: "IV17–IV19 have labels but no model run",
              detail:
                "The three cases added in investigation-eval-v2 exist to test the policy boundary. No investigator has been scored against them, and no metric on this page includes them.",
            },
            {
              title: "Evaluation version matters",
              detail:
                "Every metric above was measured against investigation-eval-v1, which is frozen and hash-pinned. eval-v2 re-labels four cases and adds three; comparing a number from one version against a number from the other would be comparing different questions.",
            },
          ]}
        />
      </Group>

      <Group
        step={6}
        title="Action policy — system safety"
        lead="The deterministic gate between a model recommendation and an approvable action. This is business logic, not a model, so anything below 100% on the authored suite is a defect rather than a limitation."
      >
        <Suite
          title="Policy suite"
          description="Allowed action type, target existence, evidence sufficiency, abstention gating, incident state. Both rate metrics count failures — lower is better."
          result={policy}
        />
        {policyReplay.ok && <PolicyComparison report={policyReplay.data} />}
        <Caveats
          items={[
            {
              title: "Policy does not catch every model mistake, and should not",
              detail:
                "Action-specific policy blocked none of v2's three unsupported restarts, because each landed on a service whose error signature genuinely indicates a stalled worker — the one mechanism a restart addresses. Those were diagnosis failures, not unsafe actions. A gate on action support is the wrong place to fix a model that concluded when it should have abstained.",
            },
            {
              title: "Evidence collection is time-blind",
              detail:
                "Operational evidence is gathered per service, not per time window, so two incidents on the same service minutes apart receive identical signals. That is why IV04 and IV12 could not be told apart and had to be adjudicated rather than distinguished.",
            },
            {
              title: "The policy replay reconstructs citations",
              detail:
                "The recorded run stored each case's action type but not the evidence ids the model cited, so the replay has each recommendation cite the entire registry — the most generous input available. Eligibility there is an upper bound, not the exact historical result.",
            },
          ]}
        />
      </Group>

      <Group
        step={7}
        title="Native label capture"
        lead="Not a result — a mechanism. Three attempts to recover paraphrases automatically failed, and the last of them showed why: the labels were borrowed from a dataset answering a different question."
      >
        <Caveats
          items={[
            {
              title: "Why borrowed supervision did not transfer",
              detail:
                "The pairwise classifier improved ranking (50% to 74.2% held-out ordering) but positive/hard-negative separation stayed negative and the development threshold did not transfer. Its service_conflict coefficient came out positive, which is domain nonsense. That is what labels at the wrong granularity look like — it cannot establish that discriminative modelling fails, only that those labels were insufficient.",
            },
            {
              title: "What operator review captures instead",
              detail:
                "Every confirm or reject records the runtime's own question: given this ticket and this candidate as they existed at decision time, do they belong together? The candidate state, its members, the deterministic signals and 26 pairwise features are stored immutably alongside the decision, so a label stays reconstructable after the incident has moved on.",
            },
            {
              title: "The sample is deliberately not random",
              detail:
                "Reviews exist only where the structural gate found a candidate plausible and automation declined. Near-duplicates and hard conflicts never reach an operator. The base rate of this data therefore carries no information about correlation in general, and anything trained on it has to account for that.",
            },
            {
              title: "Nothing is retrained automatically",
              detail:
                "The exporter reports how many labels exist and declines to call them model-ready. A supervised fallback should wait for enough independent labels to support a grouped train/dev/test split with hard negatives across several services and mechanisms. A handful of clicked examples is not a dataset.",
            },
          ]}
        />
      </Group>
    </div>
  );
}

function Group({
  step,
  title,
  lead,
  children,
}: {
  step: number;
  title: string;
  lead: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div className="border-b border-neutral-300 pb-2 dark:border-neutral-700">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-neutral-400 tabular-nums dark:text-neutral-600">
            {String(step).padStart(2, "0")}
          </span>
          <h2 className="text-base font-semibold">{title}</h2>
        </div>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">{lead}</p>
      </div>
      {children}
    </section>
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
        <h3 className="text-sm font-semibold">{title}</h3>
        <ApiError error={result.error} />
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          If the API is running, the artifact may not have been generated yet — run the
          matching <code>scripts/evaluate_*.py</code> in <code>apps/api</code>.
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
    <header className="space-y-2">
      <h1 className="text-xl font-semibold">Evals</h1>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Measured results read from the artifacts the offline harness produced, in the
        order the system was built. Model quality and system safety are scored separately
        and deliberately: a model that recommends nothing and a policy that blocks
        everything both look perfect on the other&apos;s terms.
      </p>
      <div className="flex flex-wrap gap-2">
        <Badge>investigation-eval-v1 · frozen</Badge>
        <Badge tone="info">investigation-eval-v2 · adjudicated</Badge>
        <Badge>action-policy-v2 · in force</Badge>
      </div>
      <p className="text-xs text-neutral-500">
        Figures come from committed artifacts except the Polaris comparison, which is
        marked where it appears — that corpus is CC BY-SA and is not redistributed, so its
        report stays out of the repository.
      </p>
    </header>
  );
}
