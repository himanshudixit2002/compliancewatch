import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { CONSENT_PURPOSES } from "@/entities/consent/types";
import { VERSIONS } from "@/test/consent-fixture";
import {
  ONBOARDING_PURPOSES,
  OPTIONAL_PURPOSES,
  PURPOSE_DOCUMENT,
  REQUIRED_PURPOSES,
  checkboxLabel,
  isRequiredPurpose,
  noticeFor,
  noticeVersionOf,
  purposeLabel,
} from "./purposes";

const LEGAL = resolve(__dirname, "../../../../../../docs/legal");

describe("purposes", () => {
  it("asks for every identity purpose, the three required ones first", () => {
    expect([...ONBOARDING_PURPOSES].sort()).toEqual([...CONSENT_PURPOSES].sort());
    expect(ONBOARDING_PURPOSES.slice(0, 3)).toEqual(REQUIRED_PURPOSES);
    expect(OPTIONAL_PURPOSES).toEqual(["whatsapp_reminders", "email_reminders", "analytics"]);
    expect(isRequiredPurpose("profile_processing")).toBe(true);
    expect(isRequiredPurpose("analytics")).toBe(false);
  });

  it("names each purpose and gives its checkbox sentence", () => {
    expect(purposeLabel("profile_processing")).toBe("Processing of the business profile");
    expect(checkboxLabel("terms")).toBe("I accept the terms of service.");
  });

  it("uses the onboarding checkbox wording docs/legal/whatsapp-consent.md publishes", () => {
    const published = readFileSync(resolve(LEGAL, "whatsapp-consent.md"), "utf8");
    expect(published).toContain(checkboxLabel("whatsapp_reminders"));
  });

  it("builds the notice version from the document and its Version line", () => {
    expect(noticeVersionOf("terms-of-service", "0.1-draft")).toBe("terms-of-service@0.1-draft");
    expect(() => noticeVersionOf("terms-of-service", "1".repeat(30))).toThrow(/longer than 40/);
    expect(noticeFor("terms", VERSIONS)).toBe("terms-of-service@9.9");
    expect(noticeFor("profile_processing", VERSIONS)).toBe("privacy-notice@9.9-draft");
    expect(noticeFor("whatsapp_reminders", VERSIONS)).toBe("whatsapp-consent@9.8-draft");
    for (const purpose of ONBOARDING_PURPOSES) {
      expect(Object.keys(VERSIONS)).toContain(PURPOSE_DOCUMENT[purpose]);
    }
  });
});
