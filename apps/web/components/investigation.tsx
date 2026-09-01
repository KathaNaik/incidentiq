import { Badge } from "@/components/badge";
import { PolicyProbe } from "@/components/policy-probe";
import { Disclosure } from "@/components/disclosure";
import { TemporalEvidence } from "@/components/temporal-evidence";
import { RemediationWorkflow } from "@/components/remediation-workflow";
import type { EvidenceItem, InvestigationResult } from "@/lib/api";

const KIND_LABELS: Record<string, string> = {
  ticket: "Ticket",
  correlation: "Correlation",
  deployment: "Deployment",
  health: "Service health",
  error: "Error signature",
  historical: "Past incident",
  temporal: "Derived chronology",
};

/**
 * The investigation panel.
 *
 * Observed evidence and model hypothesis are visually separate sections — a past
 * incident's root cause is a fact about *that* incident, and must never read as a
 * finding about this one.
 *
 * Remediation is delegated to `RemediationWorkflow`, which puts the recommendation
 * behind deterministic policy and two explicit human decisions. Nothing here executes
 * anything on its own.
 */
export function Investigation({
  result,
  serviceId,
  investigationRunId,
  readOnly = false,
}: {
  result: InvestigationResult;
  serviceId: string | null;
  investigationRunId: string;
  /** True when viewing a superseded run: its conclusions are history, not a proposal. */
  readOnly?: boolean;
}) {
  const { output, evidence } = result;
  const byId = new Map(evidence.map((item) => [item.id, item]));
  // What was seen, versus what was derived from when it was seen. Two different kinds of
  // thing, so two sections.
  const observed = evidence.filter((item) => item.kind !== "temporal");

  const temporalCount = evidence.length - observed.length;
  const cited = new Set(
    output.hypotheses.flatMap((h) => h.supporting_evidence_ids),
  );

  return (
    <section className="space-y-4">
      {/* Conclusion first, evidence after. The model's answer is what an operator opened
          the page for; the 23 records behind it are how they check it. Both matter, in
          that order. */}
      <p className="text-xs text-neutral-500">
        {observed.length} observations · {temporalCount} temporal relationships ·{" "}
        {cited.size} citation{cited.size === 1 ? "" : "s"}, all validated against the
        evidence registry
      </p>

      {/* ---- model output: clearly a hypothesis ---- */}
      {output.abstain ? (
        <div className="rounded border border-amber-300 p-4 dark:border-amber-900">
          <h3 className="text-sm font-medium">Insufficient evidence — no conclusion</h3>
          <p className="mt-1 text-sm text-neutral-700 dark:text-neutral-300">
            {output.abstain_reason ??
              "The evidence does not support naming a cause for this incident."}
          </p>
          {output.missing_evidence.length > 0 && (
            <>
              <p className="mt-3 text-xs font-medium tracking-wide text-neutral-500 uppercase">
                Missing evidence
              </p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-neutral-700 dark:text-neutral-300">
                {output.missing_evidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs font-medium tracking-wide text-neutral-500 uppercase">
            Model hypotheses — inference, not observation
          </p>
          {output.hypotheses.map((hypothesis, index) => (
            <article
              key={hypothesis.summary}
              className="rounded border border-neutral-300 p-4 dark:border-neutral-700"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={index === 0 ? "info" : "neutral"}>
                  {index === 0 ? "Leading hypothesis" : `Alternative ${index + 1}`}
                </Badge>
                <span className="text-xs text-neutral-500">
                  Model confidence {hypothesis.confidence.toFixed(2)} — the model&apos;s
                  own estimate, not a calibrated probability
                </span>
              </div>
              <p className="mt-2 text-sm text-neutral-800 dark:text-neutral-200">
                {hypothesis.summary}
              </p>

              <CitedEvidence
                label="Supporting evidence"
                ids={hypothesis.supporting_evidence_ids}
                byId={byId}
              />
              {hypothesis.conflicting_evidence_ids.length > 0 && (
                <CitedEvidence
                  label="Conflicting evidence"
                  ids={hypothesis.conflicting_evidence_ids}
                  byId={byId}
                  tone="conflict"
                />
              )}
            </article>
          ))}
        </div>
      )}

      <div className="rounded border border-neutral-300 p-4 dark:border-neutral-700">
        <h3 className="text-sm font-medium">Recommended next step</h3>
        <p className="mt-1 text-sm text-neutral-700 dark:text-neutral-300">
          {output.recommended_next_step.description}
        </p>
        <p className="mt-1 text-xs text-neutral-500">
          {output.recommended_next_step.rationale}
        </p>
      </div>

      {/* Temporal relationships stay visible rather than collapsed: the chain from a
          deployment to the first symptom is the strongest thing this product derives, and
          it is what makes the hypothesis checkable at a glance. */}
      <TemporalEvidence evidence={evidence} />

      <Disclosure
        summary="Observed evidence"
        hint={`${observed.length} records the model was given`}
      >
        <ul className="space-y-2">
          {observed.map((item) => (
            <EvidenceRow key={item.id} item={item} />
          ))}
        </ul>
      </Disclosure>

      <RemediationWorkflow
        result={result}
        serviceId={serviceId}
        investigationRunId={investigationRunId}
        readOnly={readOnly}
      />

      {!readOnly && <PolicyProbe investigation={result} serviceId={serviceId} />}

      <p className="text-xs text-neutral-500">
        {result.version} · model {result.run.model} · prompt {result.run.prompt_version} ·{" "}
        {result.run.latency_ms} ms
        {result.run.input_tokens !== null &&
          ` · ${result.run.input_tokens} in / ${result.run.output_tokens} out tokens`}
      </p>
    </section>
  );
}

function EvidenceRow({ item }: { item: EvidenceItem }) {
  return (
    <li className="text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <code className="text-xs text-neutral-500">{item.id}</code>
        <Badge>{KIND_LABELS[item.kind] ?? item.kind}</Badge>
        <span className="text-xs text-neutral-500">{item.provenance}</span>
      </div>
      <p className="mt-1 text-neutral-700 dark:text-neutral-300">{item.summary}</p>
    </li>
  );
}

function CitedEvidence({
  label,
  ids,
  byId,
  tone = "support",
}: {
  label: string;
  ids: string[];
  byId: Map<string, EvidenceItem>;
  tone?: "support" | "conflict";
}) {
  if (ids.length === 0) return null;
  const marker = tone === "conflict" ? "−" : "+";
  const colour =
    tone === "conflict"
      ? "text-amber-700 dark:text-amber-500"
      : "text-green-700 dark:text-green-500";

  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-xs font-medium tracking-wide text-neutral-500 uppercase">
        {label} ({ids.length})
      </summary>
      <ul className="mt-2 space-y-1 text-sm">
        {ids.map((id) => {
          const item = byId.get(id);
          return (
            <li key={id}>
              <span className={colour}>{marker}</span>{" "}
              <code className="text-xs text-neutral-500">{id}</code>{" "}
              {item ? item.summary : "(evidence not found)"}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
