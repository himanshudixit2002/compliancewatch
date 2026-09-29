import type {
  ConsentRecordDto,
  ConsentStateDto,
  ConsentSummaryDto,
} from "@/entities/consent/types";
import type { LegalDocName } from "@/shared/config/legal-docs";

/**
 * Consent summaries and document versions for unit tests. The versions are synthetic ("9.9"),
 * so a test never depends on the drafts' real Version lines; the real ones are read by the
 * legal loader's own test and by the e2e suite.
 */
export const OWNER_ID = "7c1e2d3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f";

export const VERSIONS = {
  "privacy-notice": {
    name: "privacy-notice",
    title: "Privacy notice",
    version: "9.9-draft",
    isDraft: true,
  },
  "terms-of-service": {
    name: "terms-of-service",
    title: "Terms of service",
    version: "9.9",
    isDraft: false,
  },
  "whatsapp-consent": {
    name: "whatsapp-consent",
    title: "WhatsApp consent",
    version: "9.8-draft",
    isDraft: true,
  },
} as const satisfies Record<
  LegalDocName,
  { name: LegalDocName; title: string; version: string; isDraft: boolean }
>;

export function grantedState(
  purpose: ConsentStateDto["purpose"],
  noticeVersion: string,
  granted = true,
): ConsentStateDto {
  return {
    purpose,
    granted,
    notice_version: noticeVersion,
    since: "2000-01-01T00:00:00Z",
    source: "web_onboarding",
  };
}

export function summaryDto(
  states: ConsentStateDto[] = [],
  history: ConsentRecordDto[] = [],
): ConsentSummaryDto {
  return { subject: OWNER_ID, states, history };
}

/** Every required purpose granted at the fixture's versions. */
export const ACCEPTED_STATES: ConsentStateDto[] = [
  grantedState("terms", "terms-of-service@9.9"),
  grantedState("privacy_notice", "privacy-notice@9.9-draft"),
  grantedState("profile_processing", "privacy-notice@9.9-draft"),
];

let recordCount = 0;

/** One history row as the service returns it; ids count up so each row has its own. */
export function recordDto(
  purpose: ConsentRecordDto["purpose"],
  granted: boolean,
  noticeVersion: string,
  overrides: Partial<ConsentRecordDto> = {},
): ConsentRecordDto {
  recordCount += 1;
  return {
    id: `00000000-0000-4000-8000-${String(recordCount).padStart(12, "0")}`,
    subject: OWNER_ID,
    purpose,
    granted,
    source: "web_onboarding",
    notice_version: noticeVersion,
    evidence: "Example evidence",
    recorded_by: OWNER_ID,
    recorded_at: "2000-01-01T00:00:00Z",
    ...overrides,
  };
}
