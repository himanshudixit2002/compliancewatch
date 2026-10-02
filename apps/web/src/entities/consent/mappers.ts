import {
  CONSENT_PURPOSES,
  type ConsentInDto,
  type ConsentPurpose,
  type ConsentRecord,
  type ConsentRecordDto,
  type ConsentState,
  type ConsentSummary,
  type ConsentSummaryDto,
  type NewConsent,
} from "./types";

export function isConsentPurpose(value: string): value is ConsentPurpose {
  return (CONSENT_PURPOSES as readonly string[]).includes(value);
}

export function consentRecordFromDto(dto: ConsentRecordDto): ConsentRecord {
  return {
    id: dto.id,
    subject: dto.subject,
    purpose: dto.purpose,
    granted: dto.granted,
    source: dto.source,
    noticeVersion: dto.notice_version,
    evidence: dto.evidence,
    recordedBy: dto.recorded_by ?? null,
    recordedAt: dto.recorded_at,
  };
}

export function consentSummaryFromDto(dto: ConsentSummaryDto): ConsentSummary {
  return {
    subject: dto.subject,
    states: dto.states.map((state): ConsentState => ({
      purpose: state.purpose,
      granted: state.granted,
      noticeVersion: state.notice_version,
      since: state.since,
      source: state.source,
    })),
    history: dto.history.map(consentRecordFromDto),
  };
}

export function newConsentToDto(input: NewConsent): ConsentInDto {
  return {
    subject: input.subject,
    purpose: input.purpose,
    granted: input.granted,
    source: input.source,
    notice_version: input.noticeVersion,
    evidence: input.evidence,
    recorded_by: input.recordedBy,
  };
}

/** The current state of one purpose, or undefined when nothing was ever recorded for it. */
export function stateOf(
  summary: ConsentSummary,
  purpose: ConsentPurpose,
): ConsentState | undefined {
  return summary.states.find((state) => state.purpose === purpose);
}

/** True when the latest record grants the purpose at exactly this notice version. */
export function isGrantedAt(
  summary: ConsentSummary,
  purpose: ConsentPurpose,
  noticeVersion: string,
): boolean {
  const state = stateOf(summary, purpose);
  return state !== undefined && state.granted && state.noticeVersion === noticeVersion;
}
