import type { identity } from "@compliancewatch/contracts/openapi";

/**
 * Consent records on the identity service (docs/legal/consent-record.md): append-only rows of
 * what a subject agreed to or withdrew from, per purpose, with the version of the notice they
 * saw, the source, the evidence and who recorded it. The latest row per purpose is the state.
 * A withdrawal is a new row with `granted: false`, never an edit.
 */
type Schemas = identity.components["schemas"];

export type ConsentSummaryDto = Schemas["ConsentSummaryOut"];
export type ConsentRecordDto = Schemas["ConsentOut"];
export type ConsentStateDto = Schemas["ConsentStateOut"];
export type ConsentInDto = Schemas["ConsentIn"];

export type ConsentPurpose = Schemas["ConsentPurpose"];
export type ConsentSource = Schemas["ConsentSource"];

/** The identity service's purposes, in the order the onboarding asks for them. */
export const CONSENT_PURPOSES: readonly ConsentPurpose[] = [
  "terms",
  "privacy_notice",
  "profile_processing",
  "whatsapp_reminders",
  "email_reminders",
  "analytics",
];

/** The longest notice_version the service stores. */
export const NOTICE_VERSION_MAX_LENGTH = 40;

export interface ConsentState {
  purpose: ConsentPurpose;
  granted: boolean;
  noticeVersion: string;
  /** When the latest row was recorded. */
  since: string;
  source: ConsentSource;
}

export interface ConsentRecord {
  id: string;
  subject: string;
  purpose: ConsentPurpose;
  granted: boolean;
  source: ConsentSource;
  noticeVersion: string;
  evidence: string;
  recordedBy: string | null;
  recordedAt: string;
}

export interface ConsentSummary {
  subject: string;
  states: readonly ConsentState[];
  /** Every row, oldest first. */
  history: readonly ConsentRecord[];
}

export interface NewConsent {
  /** A user id, or an E.164 number. */
  subject: string;
  purpose: ConsentPurpose;
  granted: boolean;
  source: ConsentSource;
  /** Required when granting. */
  noticeVersion: string;
  /** What the person saw: the checkbox label, the keyword, the support ticket. */
  evidence: string;
  /** The user who recorded it. */
  recordedBy: string;
}
