import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  consentRecordFromDto,
  consentSummaryFromDto,
  isConsentPurpose,
  isGrantedAt,
  newConsentToDto,
  stateOf,
} from "./mappers";
import { CONSENT_PURPOSES } from "./types";
import type { ConsentPurpose, ConsentRecordDto, ConsentSummaryDto } from "./types";

const USER = "7c1e2d3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f";

const RECORD: ConsentRecordDto = {
  id: "00000000-0000-4000-8000-000000000c01",
  subject: USER,
  purpose: "terms",
  granted: true,
  source: "web_onboarding",
  notice_version: "terms-of-service@0.1-draft",
  evidence: "Example label",
  recorded_by: USER,
  recorded_at: "2000-01-01T00:00:00Z",
};

const SUMMARY: ConsentSummaryDto = {
  subject: USER,
  states: [
    {
      purpose: "terms",
      granted: true,
      notice_version: "terms-of-service@0.1-draft",
      since: "2000-01-01T00:00:00Z",
      source: "web_onboarding",
    },
    {
      purpose: "analytics",
      granted: false,
      notice_version: "privacy-notice@0.1-draft",
      since: "2000-01-02T00:00:00Z",
      source: "web_onboarding",
    },
  ],
  history: [RECORD],
};

describe("consent mappers", () => {
  it("maps a summary with its states and history", () => {
    const summary = consentSummaryFromDto(SUMMARY);
    expect(summary.subject).toBe(USER);
    expect(summary.states[0]).toEqual({
      purpose: "terms",
      granted: true,
      noticeVersion: "terms-of-service@0.1-draft",
      since: "2000-01-01T00:00:00Z",
      source: "web_onboarding",
    });
    expect(summary.history[0]).toEqual({
      id: RECORD.id,
      subject: USER,
      purpose: "terms",
      granted: true,
      source: "web_onboarding",
      noticeVersion: "terms-of-service@0.1-draft",
      evidence: "Example label",
      recordedBy: USER,
      recordedAt: "2000-01-01T00:00:00Z",
    });
    expect(consentRecordFromDto({ ...RECORD, recorded_by: null }).recordedBy).toBeNull();
  });

  it("builds the body of a new record", () => {
    expect(
      newConsentToDto({
        subject: USER,
        purpose: "privacy_notice",
        granted: true,
        source: "web_onboarding",
        noticeVersion: "privacy-notice@0.1-draft",
        evidence: "Example label",
        recordedBy: USER,
      }),
    ).toEqual({
      subject: USER,
      purpose: "privacy_notice",
      granted: true,
      source: "web_onboarding",
      notice_version: "privacy-notice@0.1-draft",
      evidence: "Example label",
      recorded_by: USER,
    });
  });

  it("reads one purpose's state and whether it is granted at a version", () => {
    const summary = consentSummaryFromDto(SUMMARY);
    expect(stateOf(summary, "terms")?.granted).toBe(true);
    expect(stateOf(summary, "email_reminders")).toBeUndefined();
    expect(isGrantedAt(summary, "terms", "terms-of-service@0.1-draft")).toBe(true);
    expect(isGrantedAt(summary, "terms", "terms-of-service@0.2")).toBe(false);
    expect(isGrantedAt(summary, "analytics", "privacy-notice@0.1-draft")).toBe(false);
    expect(isGrantedAt(summary, "email_reminders", "privacy-notice@0.1-draft")).toBe(false);
  });

  it("lists exactly the identity spec's purposes", () => {
    const spec = JSON.parse(
      readFileSync(
        resolve(__dirname, "../../../../../packages/contracts/openapi/identity.v1.json"),
        "utf8",
      ),
    ) as { components: { schemas: { ConsentPurpose: { enum: ConsentPurpose[] } } } };
    expect([...CONSENT_PURPOSES].sort()).toEqual(
      [...spec.components.schemas.ConsentPurpose.enum].sort(),
    );
    expect(isConsentPurpose("analytics")).toBe(true);
    expect(isConsentPurpose("marketing")).toBe(false);
  });
});
