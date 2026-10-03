import type { Tone } from "@compliancewatch/ui";
import type { MessageKey } from "@/shared/i18n";

/**
 * The data rights screen's model: the requests made under India's Digital Personal Data
 * Protection Act for a copy of the account's personal data or for its deletion, as
 * `GET /v1/identity/data-requests` (awaited) would list them. A request is due 30 days after it
 * is made; a completed copy is downloaded from `GET /v1/identity/data-requests/{id}/export`.
 */
export type DataRequestKind = "export" | "deletion";

export type DataRequestStatus = "received" | "in_progress" | "completed" | "declined";

export interface DataRequest {
  id: string;
  kind: DataRequestKind;
  status: DataRequestStatus;
  /** When the request was recorded, an ISO instant. */
  requestedAt: string;
  /** When it must be complete by, an ISO instant. */
  dueBy: string;
  /** When it was completed or declined; null while it is open. */
  closedAt: string | null;
}

export const DATA_REQUEST_KINDS: readonly DataRequestKind[] = ["export", "deletion"];

/**
 * The form fields the request action reads: the kind, and for a deletion the box that says the
 * person understands it cannot be undone (the action should refuse a deletion without it).
 */
export const DATA_REQUEST_FIELDS = { kind: "kind", confirm: "confirm_deletion" } as const;

export const KIND_LABEL: Readonly<Record<DataRequestKind, MessageKey>> = {
  export: "dataRights.kind.export",
  deletion: "dataRights.kind.deletion",
};

export const STATUS_LABEL: Readonly<Record<DataRequestStatus, MessageKey>> = {
  received: "dataRights.status.received",
  in_progress: "dataRights.status.inProgress",
  completed: "dataRights.status.completed",
  declined: "dataRights.status.declined",
};

export const STATUS_TONE: Readonly<Record<DataRequestStatus, Tone>> = {
  received: "info",
  in_progress: "warning",
  completed: "success",
  declined: "danger",
};

/** Received or in progress: not yet completed or declined. */
export function isOpen(request: Pick<DataRequest, "status">): boolean {
  return request.status === "received" || request.status === "in_progress";
}

/** The open request of a kind, if any; a second one of the same kind is not asked for. */
export function openRequestOf(
  requests: readonly DataRequest[],
  kind: DataRequestKind,
): DataRequest | undefined {
  return requests.find((request) => request.kind === kind && isOpen(request));
}

/** The most recent request first. */
export function newestFirst(requests: readonly DataRequest[]): DataRequest[] {
  return [...requests].sort((a, b) => Date.parse(b.requestedAt) - Date.parse(a.requestedAt));
}
