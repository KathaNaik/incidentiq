import type {
  IncidentSeverity,
  IncidentStatus,
  Service,
  TicketPriority,
  TicketStatus,
} from "@/lib/api";

/**
 * Timestamps render in UTC. Operators compare them against logs and each other, and a
 * fixed zone also keeps server and client output identical.
 */
const TIMESTAMP_FORMAT = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

export function formatTimestamp(iso: string): string {
  return `${TIMESTAMP_FORMAT.format(new Date(iso))} UTC`;
}

const TICKET_STATUS_LABELS: Record<TicketStatus, string> = {
  open: "Open",
  in_progress: "In progress",
  resolved: "Resolved",
};

const TICKET_PRIORITY_LABELS: Record<TicketPriority, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

const INCIDENT_STATUS_LABELS: Record<IncidentStatus, string> = {
  investigating: "Investigating",
  identified: "Identified",
  monitoring: "Monitoring",
  resolved: "Resolved",
};

const INCIDENT_SEVERITY_LABELS: Record<IncidentSeverity, string> = {
  sev1: "SEV1",
  sev2: "SEV2",
  sev3: "SEV3",
};

export const ticketStatusLabel = (status: TicketStatus) =>
  TICKET_STATUS_LABELS[status];

/** Unknown priority is shown as unknown, never silently downgraded to a value. */
export const ticketPriorityLabel = (priority: TicketPriority | null) =>
  priority === null ? "Untriaged" : TICKET_PRIORITY_LABELS[priority];

export const incidentStatusLabel = (status: IncidentStatus) =>
  INCIDENT_STATUS_LABELS[status];

export const incidentSeverityLabel = (severity: IncidentSeverity) =>
  INCIDENT_SEVERITY_LABELS[severity];

export function serviceNames(services: Service[]): Map<string, string> {
  return new Map(services.map((service) => [service.id, service.name]));
}

export const serviceLabel = (names: Map<string, string>, id: string | null) =>
  id === null ? "Unassigned" : (names.get(id) ?? id);
