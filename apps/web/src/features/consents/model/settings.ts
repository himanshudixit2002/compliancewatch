import { stateOf } from "@/entities/consent/mappers";
import {
  CONSENT_PURPOSES,
  type ConsentPurpose,
  type ConsentRecord,
  type ConsentSource,
  type ConsentSummary,
} from "@/entities/consent/types";
import type { TenantKind } from "@/shared/config/roles";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { draftDocuments, purposesFor } from "./consent-step";
import {
  PURPOSE_DOCUMENT,
  checkboxLabel,
  isRequiredPurpose,
  noticeFor,
  purposeLabel,
  type DocumentVersion,
  type DocumentVersions,
} from "./purposes";

/**
 * What the consents settings page shows, from the user's consent records and the documents'
 * current versions: one row per purpose with its latest record, and every record oldest first.
 *
 * The required purposes (terms, privacy notice, profile processing) are shown but not changed
 * here: the service runs on them, so withdrawing them is a data rights request. The optional
 * ones (WhatsApp reminders, email reminders, product analytics) can be withdrawn when given and
 * given when not; either way the page adds a record and never edits one. A CA firm is not
 * offered WhatsApp reminders (they are set per client business), but a record already on file
 * is still shown and can be withdrawn.
 */
export type ConsentStatus = "granted" | "withdrawn" | "not_given";
export type ConsentChange = "withdraw" | "give";

export interface ConsentRowView {
  purpose: ConsentPurpose;
  label: string;
  required: boolean;
  status: ConsentStatus;
  /** The latest record's notice version; null when nothing is recorded. */
  noticeVersion: string | null;
  /** When the latest record was written, in IST; null when nothing is recorded. */
  since: string | null;
  source: string | null;
  /** The notice version this build asks for. */
  currentNoticeVersion: string;
  /** Given, but for an earlier notice version than the current document. */
  outdated: boolean;
  /** What the page offers for the purpose; null for the required ones. */
  change: ConsentChange | null;
  /** The sentence the person confirms, which the record keeps inside its evidence. */
  statement: string;
  document: DocumentVersion;
}

export interface ConsentHistoryItem {
  id: string;
  purpose: ConsentPurpose;
  label: string;
  granted: boolean;
  noticeVersion: string | null;
  source: string;
  evidence: string;
  recordedAt: string;
  /** "you" for the signed-in user, the id of anyone else, null when no recorder was sent. */
  recordedBy: "you" | string | null;
}

export interface ConsentSettingsView {
  rows: readonly ConsentRowView[];
  /** Every record, oldest first. */
  history: readonly ConsentHistoryItem[];
  drafts: readonly DocumentVersion[];
  /** The WhatsApp number this device remembers for the user, "+91...", or "". */
  whatsappNumber: string;
}

export function sourceLabel(source: ConsentSource): string {
  return t(`consent.source.${source}`);
}

/** The sentence a change is confirmed with: the checkbox wording to give, a plain one to withdraw. */
export function changeStatement(purpose: ConsentPurpose, change: ConsentChange): string {
  return change === "give"
    ? checkboxLabel(purpose)
    : t("consentSettings.withdrawStatement", { purpose: purposeLabel(purpose) });
}

/** The evidence a change records: where it was confirmed and the sentence confirmed. */
export function changeEvidence(purpose: ConsentPurpose, change: ConsentChange): string {
  return t("consentSettings.evidence", { statement: changeStatement(purpose, change) });
}

function rowPurposes(summary: ConsentSummary, tenantKind: TenantKind): ConsentPurpose[] {
  const asked = purposesFor(tenantKind);
  return CONSENT_PURPOSES.filter(
    (purpose) => asked.includes(purpose) || stateOf(summary, purpose) !== undefined,
  );
}

function statusOf(summary: ConsentSummary, purpose: ConsentPurpose): ConsentStatus {
  const state = stateOf(summary, purpose);
  if (state === undefined) return "not_given";
  return state.granted ? "granted" : "withdrawn";
}

function changeFor(
  purpose: ConsentPurpose,
  status: ConsentStatus,
  offered: readonly ConsentPurpose[],
): ConsentChange | null {
  if (isRequiredPurpose(purpose)) return null;
  if (status === "granted") return "withdraw";
  return offered.includes(purpose) ? "give" : null;
}

function historyItem(record: ConsentRecord, userId: string): ConsentHistoryItem {
  return {
    id: record.id,
    purpose: record.purpose,
    label: purposeLabel(record.purpose),
    granted: record.granted,
    noticeVersion: record.noticeVersion === "" ? null : record.noticeVersion,
    source: sourceLabel(record.source),
    evidence: record.evidence,
    recordedAt: formatDateTime(record.recordedAt),
    recordedBy:
      record.recordedBy === null ? null : record.recordedBy === userId ? "you" : record.recordedBy,
  };
}

export function consentSettingsView(
  summary: ConsentSummary,
  versions: DocumentVersions,
  options: { tenantKind: TenantKind; userId: string; whatsappNumber?: string },
): ConsentSettingsView {
  const offered = purposesFor(options.tenantKind);
  const purposes = rowPurposes(summary, options.tenantKind);
  const rows = purposes.map((purpose): ConsentRowView => {
    const state = stateOf(summary, purpose);
    const status = statusOf(summary, purpose);
    const currentNoticeVersion = noticeFor(purpose, versions);
    const change = changeFor(purpose, status, offered);
    return {
      purpose,
      label: purposeLabel(purpose),
      required: isRequiredPurpose(purpose),
      status,
      noticeVersion: state === undefined || state.noticeVersion === "" ? null : state.noticeVersion,
      since: state === undefined ? null : formatDateTime(state.since),
      source: state === undefined ? null : sourceLabel(state.source),
      currentNoticeVersion,
      outdated: status === "granted" && state?.noticeVersion !== currentNoticeVersion,
      change,
      statement: changeStatement(purpose, change ?? "give"),
      document: versions[PURPOSE_DOCUMENT[purpose]],
    };
  });
  return {
    rows,
    history: summary.history.map((record) => historyItem(record, options.userId)),
    drafts: draftDocuments(purposes, versions),
    whatsappNumber: options.whatsappNumber ?? "",
  };
}
