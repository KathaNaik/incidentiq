/**
 * Client for the IncidentIQ FastAPI backend.
 *
 * The base URL is read from the environment so the web app never assumes the API is
 * co-located with it.
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001";

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
  kind: "ticket" | "correlation" | "deployment" | "health" | "error" | "historical";
  summary: string;
  source_id: string;
  provenance: string;
  observed_at: string | null;
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

export type PolicyReason = { check: string; passed: boolean; detail: string };

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

export async function investigateCandidate(
  candidateId: string,
  mode: CorrelationMode = "deterministic",
): Promise<InvestigationResult> {
  const response = await fetch(
    `${API_BASE_URL}/correlation/candidates/${encodeURIComponent(candidateId)}/investigate?mode=${mode}`,
    { method: "POST", cache: "no-store" },
  );
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `investigation failed with ${response.status}`);
  }
  return (await response.json()) as InvestigationResult;
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

export async function proposeAction(
  incidentId: string,
  investigation: InvestigationResult,
  serviceId: string | null,
): Promise<ActionResponse> {
  return postJson<ActionResponse>(
    `/incidents/${encodeURIComponent(incidentId)}/actions`,
    { investigation, service_id: serviceId },
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
    return {
      ok: false,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
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
