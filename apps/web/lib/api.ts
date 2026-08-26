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
