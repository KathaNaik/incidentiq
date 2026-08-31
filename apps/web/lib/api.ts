/**
 * Client for the IncidentIQ FastAPI backend.
 *
 * The base URL is read from the environment so the web app never assumes the API is
 * co-located with it.
 */
/**
 * Where the API lives, which is not one answer.
 *
 * In production the web app and the API are two services in one Vercel deployment behind
 * a single origin: the platform rewrites `/api/*` to the backend, so the browser can use
 * a relative URL and never needs to know the backend's hostname. That is what keeps
 * preview deployments working without per-environment configuration, and why production
 * needs no CORS at all.
 *
 * A server component has no origin to resolve a relative URL against — it is rendering
 * inside the deployment, not in a page — so it needs an absolute one. `VERCEL_URL` is the
 * deployment's own hostname and is not exposed to the browser.
 *
 * `NEXT_PUBLIC_API_BASE_URL` overrides everything, which is how a local production build
 * (`npm run build && npm start`) is pointed back at a local FastAPI.
 */
function resolveApiBaseUrl(): string {
  const explicit = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (explicit) return explicit;

  if (typeof window !== "undefined") {
    // NODE_ENV is inlined at build time, so `next dev` keeps talking to a local API
    // while a deployed bundle uses the same origin it was served from.
    return process.env.NODE_ENV === "production" ? "/api" : "http://localhost:8001";
  }

  const deployment = process.env.VERCEL_URL;
  if (deployment) return `https://${deployment}/api`;

  return "http://localhost:8001";
}

export const API_BASE_URL = resolveApiBaseUrl();

export type TicketStatus = "open" | "in_progress" | "resolved";
export type TicketPriority = "low" | "medium" | "high" | "critical";
export type IncidentStatus =
  | "investigating"
  | "identified"
  | "monitoring"
  | "resolved";
export type IncidentSeverity = "sev1" | "sev2" | "sev3";

export type HealthResponse = {
  status: string;
  service: string;
};

export type DatasetInfo = {
  name: string;
  synthetic: boolean;
};

export type Service = {
  id: string;
  name: string;
  description: string;
};

export type Ticket = {
  id: string;
  title: string;
  description: string;
  created_at: string;
  status: TicketStatus;
  reported_by: string;
  /** Null until the ticket has been triaged. */
  priority: TicketPriority | null;
  /** Null when the reported service is not yet known. */
  service_id: string | null;
};

export type Incident = {
  id: string;
  title: string;
  status: IncidentStatus;
  severity: IncidentSeverity;
  detected_at: string;
  created_at: string;
  affected_service_ids: string[];
};

export type IncidentSummary = Incident & {
  ticket_count: number;
};

export type PredictionStatus = "classified" | "ambiguous" | "unknown" | "default";

export type TriageSignal = {
  signal_type: string;
  matched_text: string;
  normalized_value: string;
  weight: number;
  source_field: "title" | "description";
  /** "service:svc-auth", "issue_type:availability", or "priority". */
  target: string;
};

export type TriagePrediction = {
  value: string | null;
  status: PredictionStatus;
  score: number;
  margin: number;
  candidates: { value: string; score: number }[];
  explanation: string;
};

export type TriageResult = {
  ticket_id: string | null;
  version: string;
  service: TriagePrediction;
  issue_type: TriagePrediction;
  priority: TriagePrediction;
  signals: TriageSignal[];
};

export type CorrelationSignal = {
  component: "time" | "service" | "issue_type" | "lexical" | "entity" | "semantic";
  direction: "supporting" | "conflicting" | "neutral";
  score: number;
  weight: number;
  detail: string;
  values: string[];
};

export type PairwiseScore = {
  ticket_a: string;
  ticket_b: string;
  score: number;
  content_score: number;
  time_score: number;
  minutes_apart: number;
  signals: CorrelationSignal[];
};

export type CandidateIncident = {
  id: string;
  ticket_ids: string[];
  score: number;
  confidence: "high" | "medium" | "low";
  first_seen: string;
  last_seen: string;
  service_id: string | null;
  issue_type: string | null;
  ticket_count: number;
  /** Distinct reporters actually named on the tickets — null when none are. */
  distinct_reporters: number | null;
  supporting_signals: CorrelationSignal[];
  conflicting_signals: CorrelationSignal[];
  member_pairs: PairwiseScore[];
};

export type CorrelationResult = {
  version: string;
  ticket_count: number;
  candidates: CandidateIncident[];
  standalone_ticket_ids: string[];
};

export type CorrelationMode = "deterministic" | "semantic";

export type MetricDelta = {
  name: string;
  baseline: number;
  candidate: number;
  delta: number;
};

export type SliceExample = {
  kind: string;
  ticket_a: string;
  ticket_b: string;
  explanation: string;
  signals: string[];
  text: string | null;
};

export type VersionComparison = {
  suite: string;
  baseline_version: string;
  candidate_version: string;
  generated_at: string;
  ticket_count: number;
  metrics: MetricDelta[];
  slices: SliceExample[];
  notes: string[];
};

export type HistoricalIncident = {
  id: string;
  title: string;
  summary: string;
  services: string[];
  observed_errors: string[];
  occurred_at: string | null;
  provenance: "northstar-authored" | "itsm-mit";
  outcome: { root_cause: string; resolution_steps: string[] };
};

export type MatchSignal = {
  kind: string;
  detail: string;
  contribution: number;
  values: string[];
};

export type RetrievalHit = {
  rank: number;
  incident: HistoricalIncident;
  score: number;
  similarity: number;
  signals: MatchSignal[];
};

export type RetrievalResult = {
  version: string;
  provider: string;
  corpus_size: number;
  query_text: string;
  hits: RetrievalHit[];
  /** False when nothing in the corpus resembles the query closely enough to be precedent. */
  strong_match: boolean;
};

export type EvidenceItem = {
  id: string;
  kind:
    | "ticket"
    | "correlation"
    | "deployment"
    | "health"
    | "error"
    | "historical"
    /** Derived by the application from the timestamps on the others. */
    | "temporal";
  summary: string;
  source_id: string;
  provenance: string;
  observed_at: string | null;
  service_id?: string | null;
  attributes?: Record<string, string>;
};

export type Hypothesis = {
  summary: string;
  /** The model's own stated confidence — not a calibrated probability. */
  confidence: number;
  supporting_evidence_ids: string[];
  conflicting_evidence_ids: string[];
};

export type InvestigationOutput = {
  hypotheses: Hypothesis[];
  missing_evidence: string[];
  recommended_next_step: {
    action_type: string;
    description: string;
    rationale: string;
  };
  remediation: {
    action_type: string;
    description: string;
    risk: "low" | "medium" | "high";
    supporting_evidence_ids: string[];
  } | null;
  abstain: boolean;
  abstain_reason: string | null;
};

export type InvestigationResult = {
  incident_id: string;
  version: string;
  output: InvestigationOutput;
  evidence: EvidenceItem[];
  run: {
    model: string;
    prompt_version: string;
    evidence_ids: string[];
    latency_ms: number;
    input_tokens: number | null;
    output_tokens: number | null;
    started_at: string;
  };
};

export type PolicyReason = {
  check: string;
  passed: boolean;
  detail: string;
  /** Evidence the check actually read. Empty for checks that read none. */
  evidence_ids: string[];
};

export type ActionPolicyDecision = {
  eligible: boolean;
  decision: "eligible_for_approval" | "rejected_by_policy" | "requires_more_evidence";
  reasons: PolicyReason[];
  effective_risk: "low" | "medium" | "high";
  required_approvals: number;
  validated_target: { service_id: string; deployment_id: string | null; version: string | null } | null;
  validated_evidence_ids: string[];
  evidence_source_kinds: string[];
};

export type IncidentAction = {
  id: string;
  incident_id: string;
  action_type: string;
  target: { service_id: string; deployment_id: string | null; version: string | null };
  status:
    | "proposed" | "policy_rejected" | "awaiting_approval" | "approved"
    | "rejected" | "executing" | "succeeded" | "failed";
  risk: "low" | "medium" | "high";
  created_at: string;
  recommendation_summary: string;
  recommendation_evidence_ids: string[];
  policy: ActionPolicyDecision;
  approval: {
    id: string; approved: boolean; actor_type: string; actor_id: string;
    decided_at: string; reason: string | null;
  } | null;
  execution: {
    simulated: boolean; succeeded: boolean; summary: string;
    details: string[]; executed_at: string;
  } | null;
};

export type ActionResponse = {
  action: IncidentAction;
  actor: { actor_id: string; note: string };
};

export type AuditEvent = {
  id: string;
  incident_id: string;
  action_id: string | null;
  event_type: string;
  actor_type: "system" | "model" | "human";
  actor_id: string;
  occurred_at: string;
  details: Record<string, string>;
};

export type EvalMetric = {
  name: string;
  correct: number;
  total: number;
  accuracy: number;
  abstained: number;
  majority_baseline: number | null;
};

export type EvalFailure = {
  case_id: string;
  metric: string;
  expected: string | null;
  predicted: string | null;
  status: string;
  explanation: string;
  signals: string[];
  text: string | null;
};

export type EvalReport = {
  suite: string;
  version: string;
  generated_at: string;
  case_count: number;
  metrics: EvalMetric[];
  confusion: { expected: string; predicted: string; count: number }[];
  failures: EvalFailure[];
  notes: string[];
};

/** Either the data or the reason it is unavailable — never a plausible-looking blank. */
export type Loaded<T> = { ok: true; data: T } | { ok: false; error: string };

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    signal,
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`GET ${path} responded with ${response.status}`);
  }

  return (await response.json()) as T;
}

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.status === "string" && typeof candidate.service === "string"
  );
}

/** Fetches `/health`. Throws if the API is unreachable or answers unexpectedly. */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const payload = await getJson<unknown>("/health", signal);
  if (!isHealthResponse(payload)) {
    throw new Error("Unexpected /health response shape");
  }
  return payload;
}

export async function fetchDataset(signal?: AbortSignal): Promise<DatasetInfo> {
  return getJson<DatasetInfo>("/dataset", signal);
}

export async function fetchServices(): Promise<Service[]> {
  return getJson<Service[]>("/services");
}

export async function fetchTickets(): Promise<Ticket[]> {
  return getJson<Ticket[]>("/tickets");
}

export async function fetchIncidents(): Promise<IncidentSummary[]> {
  return getJson<IncidentSummary[]>("/incidents");
}

export async function fetchTicket(ticketId: string): Promise<Ticket> {
  return getJson<Ticket>(`/tickets/${encodeURIComponent(ticketId)}`);
}

export async function fetchTicketTriage(ticketId: string): Promise<TriageResult> {
  return getJson<TriageResult>(`/tickets/${encodeURIComponent(ticketId)}/triage`);
}

export async function fetchTriageEvaluation(): Promise<EvalReport> {
  return getJson<EvalReport>("/evals/triage");
}

export async function fetchCorrelationEvaluation(
  version: CorrelationMode = "deterministic",
): Promise<EvalReport> {
  return getJson<EvalReport>(`/evals/correlation?version=${version}`);
}

export async function fetchCandidates(
  mode: CorrelationMode = "deterministic",
): Promise<CorrelationResult> {
  return getJson<CorrelationResult>(`/correlation/candidates?mode=${mode}`);
}

export async function fetchSimilarIncidents(
  candidateId: string,
  mode: CorrelationMode = "deterministic",
): Promise<RetrievalResult> {
  return getJson<RetrievalResult>(
    `/correlation/candidates/${encodeURIComponent(candidateId)}/similar?mode=${mode}`,
  );
}

export type InvestigationRunSummary = {
  id: string;
  incident_id: string;
  status: "pending" | "running" | "succeeded" | "failed";
  investigator_version: string;
  prompt_version: string;
  provider: string;
  model: string;
  evidence_schema_version: string;
  temporal_config_version: string | null;
  created_at: string;
  completed_at: string | null;
  latency_ms: number | null;
  evidence_count: number;
  abstained: boolean | null;
  recommended_action: string | null;
  failure_type: string | null;
  failure_message: string | null;
};

export type InvestigationRunDetail = InvestigationRunSummary & {
  /** Null for a failed or in-flight run. */
  result: InvestigationResult | null;
};

export type InvestigationStaleness = {
  stale: boolean;
  new_ticket_ids: string[];
  reason: string;
};

export type LatestInvestigation = {
  current: InvestigationRunDetail | null;
  active: InvestigationRunSummary | null;
  staleness?: InvestigationStaleness;
};

/**
 * Reads the stored investigation. Never starts one.
 *
 * `null` means this incident has not been investigated yet — a normal state of the
 * workflow, which the page renders as a Run button rather than as an error.
 */
export async function fetchLatestInvestigation(
  incidentId: string,
): Promise<LatestInvestigation | null> {
  const response = await fetch(
    `${API_BASE_URL}/incidents/${encodeURIComponent(incidentId)}/investigations/latest`,
    { cache: "no-store" },
  );
  if (response.status === 204) return null;
  if (!response.ok) {
    throw new Error(`GET latest investigation responded with ${response.status}`);
  }
  return (await response.json()) as LatestInvestigation;
}

export async function fetchInvestigationHistory(
  incidentId: string,
): Promise<InvestigationRunSummary[]> {
  return getJson<InvestigationRunSummary[]>(
    `/incidents/${encodeURIComponent(incidentId)}/investigations`,
  );
}

export async function fetchInvestigationRun(
  runId: string,
): Promise<InvestigationRunDetail> {
  return getJson<InvestigationRunDetail>(`/investigations/${encodeURIComponent(runId)}`);
}

/** The only call that spends a model request. Creates a new immutable run. */
export async function runInvestigation(
  incidentId: string,
  mode: CorrelationMode = "deterministic",
): Promise<InvestigationRunDetail> {
  const response = await fetch(
    `${API_BASE_URL}/incidents/${encodeURIComponent(incidentId)}/investigations?mode=${mode}`,
    { method: "POST", cache: "no-store" },
  );
  const body = await response.json().catch(() => null);
  if (!response.ok && response.status !== 409) {
    const detail = (body as { detail?: string } | null)?.detail;
    throw new Error(detail ?? `investigation failed with ${response.status}`);
  }
  return body as InvestigationRunDetail;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    cache: "no-store",
    ...(body === undefined
      ? {}
      : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const detail = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `${path} failed with ${response.status}`);
  }
  return (await response.json()) as T;
}

/**
 * Proposes an action from a *stored* investigation run.
 *
 * The client names a run rather than handing back model output: the server loads the
 * recommendation from the record that was actually produced, and links the resulting
 * action to that exact run.
 */
export async function proposeAction(
  incidentId: string,
  investigationRunId: string,
  serviceId: string | null,
): Promise<ActionResponse> {
  return postJson<ActionResponse>(
    `/incidents/${encodeURIComponent(incidentId)}/actions`,
    { investigation_run_id: investigationRunId, service_id: serviceId },
  );
}

export async function approveAction(actionId: string): Promise<ActionResponse> {
  return postJson<ActionResponse>(`/actions/${encodeURIComponent(actionId)}/approve`);
}

export async function rejectAction(actionId: string): Promise<ActionResponse> {
  return postJson<ActionResponse>(`/actions/${encodeURIComponent(actionId)}/reject`);
}

export async function executeAction(actionId: string): Promise<ActionResponse> {
  return postJson<ActionResponse>(`/actions/${encodeURIComponent(actionId)}/execute`);
}

export async function fetchActionAudit(actionId: string): Promise<AuditEvent[]> {
  return getJson<AuditEvent[]>(`/actions/${encodeURIComponent(actionId)}/audit`);
}

export async function fetchPolicyEvaluation(): Promise<EvalReport> {
  return getJson<EvalReport>("/evals/policy");
}

export async function fetchInvestigationEvaluation(
  version: "v1" | "v2" | "baseline" = "v1",
): Promise<EvalReport> {
  return getJson<EvalReport>(`/evals/investigation?version=${version}`);
}

export async function fetchRetrievalEvaluation(): Promise<EvalReport> {
  return getJson<EvalReport>("/evals/retrieval");
}

export async function fetchCorrelationComparison(): Promise<VersionComparison> {
  return getJson<VersionComparison>("/evals/correlation/comparison");
}

/** Runs a loader, turning an unreachable API into a value the page can render. */
export async function load<T>(loader: () => Promise<T>): Promise<Loaded<T>> {
  try {
    return { ok: true, data: await loader() };
  } catch (error) {
    return { ok: false, error: describeFailure(error) };
  }
}

/**
 * Turns a thrown value into something an operator can act on.
 *
 * A connection refused by a stopped backend arrives as the bare string "fetch failed",
 * which tells the reader nothing about what to do. Everything else is passed through
 * unchanged — the API's own error details are more specific than anything invented here,
 * and a stack trace is never surfaced either way.
 */
function describeFailure(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const cause =
    error instanceof Error && error.cause instanceof Error ? error.cause.message : "";
  const network =
    /fetch failed|ECONNREFUSED|ENOTFOUND|EAI_AGAIN|network|socket hang up/i;

  if (network.test(message) || network.test(cause)) {
    return `The API at ${API_BASE_URL} did not respond. It is probably not running.`;
  }
  return message || "Unknown error";
}

export type PolicyReplayVersion = {
  policy_version: string;
  recommendations: number;
  eligible: number;
  unsafe_allowed: string[];
  valid_blocked: string[];
  metrics: Record<string, number | null>;
  cases: {
    case_id: string;
    action_type: string;
    eligible: boolean;
    decision: string;
    failed_checks: string[];
    expected_actions: string[];
    unsafe_if_recommended: boolean;
  }[];
};

export type PolicyReplayReport = {
  suite: string;
  investigator_version: string;
  eval_version: string;
  generated_at: string;
  note: string;
  expected_remediation_cases: number;
  versions: PolicyReplayVersion[];
};

export async function fetchPolicyReplay(): Promise<PolicyReplayReport> {
  return getJson<PolicyReplayReport>("/evals/policy/replay");
}

export type DemoResetResult = {
  reset: boolean;
  cleared_actions: number;
  cleared_audit_events: number;
  note: string;
};

export async function fetchActions(): Promise<IncidentAction[]> {
  return getJson<IncidentAction[]>("/actions");
}

export async function resetDemoState(): Promise<DemoResetResult> {
  return postJson<DemoResetResult>("/demo/reset", {});
}

export type PolicyProbeResult = {
  action_type: string;
  hypothetical: boolean;
  policy: ActionPolicyDecision;
  note: string;
};

export async function probePolicy(
  investigation: InvestigationResult,
  actionType: string,
  serviceId: string | null,
): Promise<PolicyProbeResult> {
  return postJson<PolicyProbeResult>("/demo/policy-probe", {
    investigation,
    action_type: actionType,
    service_id: serviceId,
  });
}

export type RuntimeTicketView = {
  id: string;
  external_id: string | null;
  source: string;
  title: string;
  description: string;
  reported_by: string;
  status: string;
  created_at: string;
  received_at: string;
  reported_service_id: string | null;
  service_id: string | null;
  priority: string | null;
  issue_type: string | null;
  triage_version: string | null;
  candidate_id: string | null;
  correlation_outcome: string | null;
  correlation_reason: string | null;
  correlation_version: string | null;
  correlation_score: number | null;
};

export type TicketIntakeResult = {
  ticket: {
    id: string;
    external_id: string | null;
    source: string;
    created_at: string;
    received_at: string;
    candidate_id: string | null;
  };
  triage: {
    service_id: string | null;
    priority: string | null;
    issue_type: string | null;
    version: string;
    signals: Record<string, unknown>;
  };
  correlation: {
    ticket_id: string;
    candidate_id: string | null;
    outcome: "attached" | "created_candidate" | "uncorrelated" | "ambiguous" | "failed";
    correlation_version: string;
    score: number | null;
    confidence: string | null;
    created_new_candidate: boolean;
    supporting_signals: string[];
    conflicting_signals: string[];
    reason: string;
    alternatives: string[];
    /** Hybrid staging. Null when a single strategy decided, which had no fallback stage. */
    strategy?: string | null;
    deterministic_stage?: {
      attached: boolean;
      candidate_id: string | null;
      score: number | null;
    } | null;
    fallback_stage?: {
      semantic_invoked: boolean;
      semantic_score: number | null;
      failed: boolean;
      policy_version: string;
      decisions: {
        candidate_id: string;
        eligible: boolean;
        reasons: string[];
        blocking_reasons: string[];
      }[];
    } | null;
    embedding_model?: string | null;
  };
  candidate: Record<string, unknown> | null;
  idempotent_replay: boolean;
};

export type CreateTicketInput = {
  external_id: string;
  title: string;
  description: string;
  created_at?: string;
  reported_service_id?: string | null;
};

export async function fetchRuntimeTickets(
  params: { uncorrelated?: boolean; service_id?: string; candidate_id?: string } = {},
): Promise<RuntimeTicketView[]> {
  const query = new URLSearchParams();
  if (params.uncorrelated !== undefined) query.set("uncorrelated", String(params.uncorrelated));
  if (params.service_id) query.set("service_id", params.service_id);
  if (params.candidate_id) query.set("candidate_id", params.candidate_id);
  const suffix = query.toString() ? `?${query}` : "";
  return getJson<RuntimeTicketView[]>(`/intake/tickets${suffix}`);
}

export async function fetchRuntimeTicket(id: string): Promise<RuntimeTicketView> {
  return getJson<RuntimeTicketView>(`/intake/tickets/${encodeURIComponent(id)}`);
}

/** Submits a real report. The server owns triage and correlation; this sends neither. */
export async function submitTicket(
  input: CreateTicketInput,
): Promise<{ result: TicketIntakeResult; replayed: boolean }> {
  const response = await fetch(`${API_BASE_URL}/tickets`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = (body as { detail?: string } | null)?.detail;
    throw new Error(detail ?? `Submission failed with ${response.status}`);
  }
  return { result: body as TicketIntakeResult, replayed: response.status === 200 };
}

export type EmbeddingBakeoffModel = {
  model_id: string;
  model_name: string;
  dimension: number;
  size_gb: number | null;
  positive_min: number | null;
  positive_max: number | null;
  positive_mean: number | null;
  dangerous_min: number | null;
  dangerous_max: number | null;
  near_duplicate_min: number | null;
  near_duplicate_max: number | null;
  separation_margin: number;
  ordering_accuracy: number | null;
  separable: boolean;
};

export type EmbeddingBakeoff = {
  suite: string;
  version: string;
  generated_at: string;
  note: string;
  unsupported: Record<string, string>;
  models: EmbeddingBakeoffModel[];
};

export async function fetchEmbeddingBakeoff(): Promise<EmbeddingBakeoff> {
  return getJson<EmbeddingBakeoff>("/evals/embedding-bakeoff");
}

// --- operator correlation review ---------------------------------------------------

export type ReviewStatus = "pending" | "confirmed" | "rejected" | "stale";
export type ReviewDecision =
  | "confirm_same_incident"
  | "reject_different_incident";

/** A candidate member as the operator saw it, not as it is now. */
export type ReviewSnapshotMember = {
  id: string;
  title: string;
  description: string;
  created_at: string;
  service_id: string | null;
  issue_type: string | null;
};

export type CorrelationReview = {
  id: string;
  ticket_id: string;
  candidate_id: string;
  status: ReviewStatus;
  decision: ReviewDecision | null;
  decision_reason: string | null;
  decision_note: string | null;
  actor: string | null;
  correlation_version: string;
  review_policy_version: string;
  feature_schema: string;
  /** Pins the review to one exact candidate membership. */
  candidate_fingerprint: string;
  ticket_snapshot: {
    id: string;
    external_id: string | null;
    title: string;
    description: string;
    created_at: string;
    received_at: string;
    service_id: string | null;
    issue_type: string | null;
    priority: string | null;
    source: string;
    triage_version: string | null;
    reported_service_id: string | null;
  };
  candidate_snapshot: {
    id: string;
    title: string;
    status: string;
    score: number;
    confidence: string;
    service_id: string | null;
    issue_type: string | null;
    ticket_count: number;
    first_seen: string;
    last_seen: string;
    correlation_version: string;
    members: ReviewSnapshotMember[];
  };
  correlation_snapshot: {
    eligible: boolean;
    reasons: string[];
    blocking_reasons: string[];
    deterministic_score: number | null;
    correlation_version: string;
    review_policy_version: string;
  };
  feature_snapshot: Record<string, number>;
  created_at: string;
  decided_at: string | null;
  resulting_membership: {
    candidate_id: string;
    member_ids: string[];
    fingerprint: string;
  } | null;
};

export type ReviewDecisionResult = {
  result: {
    review: CorrelationReview;
    attached: boolean;
    candidate: {
      id: string;
      title: string;
      ticket_count: number;
      first_seen: string;
      last_seen: string;
      status: string;
    } | null;
    investigation_stale: boolean;
    superseded_review_ids: string[];
  };
  actor: { actor: string; note: string };
};

export const CONFIRM_REASONS = [
  { value: "same_symptoms", label: "Same symptoms" },
  { value: "same_mechanism", label: "Same mechanism" },
  { value: "same_rollout_or_outage", label: "Same rollout or outage" },
  { value: "other", label: "Other" },
] as const;

export const REJECT_REASONS = [
  { value: "different_mechanism", label: "Different mechanism" },
  { value: "different_service", label: "Different service" },
  { value: "timing_incompatible", label: "Timing incompatible" },
  { value: "insufficient_evidence", label: "Insufficient evidence" },
  { value: "other", label: "Other" },
] as const;

export async function fetchCorrelationReviews(
  pendingOnly = true,
): Promise<CorrelationReview[]> {
  return getJson<CorrelationReview[]>(
    `/correlation-reviews?pending_only=${pendingOnly}`,
  );
}

export async function fetchCorrelationReview(
  reviewId: string,
): Promise<CorrelationReview> {
  return getJson<CorrelationReview>(
    `/correlation-reviews/${encodeURIComponent(reviewId)}`,
  );
}

export async function confirmCorrelationReview(
  reviewId: string,
  body: { reason?: string; note?: string } = {},
): Promise<ReviewDecisionResult> {
  return postJson<ReviewDecisionResult>(
    `/correlation-reviews/${encodeURIComponent(reviewId)}/confirm`,
    body,
  );
}

export async function rejectCorrelationReview(
  reviewId: string,
  body: { reason?: string; note?: string } = {},
): Promise<ReviewDecisionResult> {
  return postJson<ReviewDecisionResult>(
    `/correlation-reviews/${encodeURIComponent(reviewId)}/reject`,
    body,
  );
}
