import { describe, expect, it } from "vitest";
import { consentSummaryFromDto } from "@/entities/consent/mappers";
import { requiredConsentsGranted } from "@/server/required-consents";
import { ACCEPTED_STATES, VERSIONS, grantedState, summaryDto } from "@/test/consent-fixture";
import {
  consentStepView,
  draftDocuments,
  grantedPurposes,
  hasAcceptedRequired,
  purposesFor,
  purposesToRecord,
} from "./consent-step";

const empty = consentSummaryFromDto(summaryDto());
const accepted = consentSummaryFromDto(summaryDto(ACCEPTED_STATES));

describe("consentStepView", () => {
  it("offers every box unticked to a new business user, required first, with its document", () => {
    const view = consentStepView(empty, VERSIONS, "business");
    expect(view.accepted).toBe(false);
    expect(view.acceptedPurposes).toEqual([]);
    expect(view.offerWhatsapp).toBe(true);
    expect(view.options.map((option) => [option.purpose, option.required, option.granted])).toEqual(
      [
        ["terms", true, false],
        ["privacy_notice", true, false],
        ["profile_processing", true, false],
        ["whatsapp_reminders", false, false],
        ["email_reminders", false, false],
        ["analytics", false, false],
      ],
    );
    expect(view.options[3]).toMatchObject({
      label: "Send me GST reminders for this business on WhatsApp. I can reply STOP at any time.",
      document: { name: "whatsapp-consent", version: "9.8-draft" },
      noticeVersion: "whatsapp-consent@9.8-draft",
      grantedAt: null,
    });
    expect(view.drafts.map((document) => document.name)).toEqual([
      "privacy-notice",
      "whatsapp-consent",
    ]);
  });

  it("leaves the WhatsApp box and its draft out for a CA firm", () => {
    const view = consentStepView(empty, VERSIONS, "ca_firm");
    expect(view.offerWhatsapp).toBe(false);
    expect(view.options.map((option) => option.purpose)).not.toContain("whatsapp_reminders");
    expect(view.drafts.map((document) => document.name)).toEqual(["privacy-notice"]);
    expect(purposesFor("internal")).not.toContain("whatsapp_reminders");
  });

  it("shows what was agreed once the required purposes are granted at the current versions", () => {
    const summary = consentSummaryFromDto(
      summaryDto([...ACCEPTED_STATES, grantedState("analytics", "privacy-notice@9.9-draft")]),
    );
    const view = consentStepView(summary, VERSIONS, "business");
    expect(view.accepted).toBe(true);
    expect(view.acceptedPurposes).toEqual([
      {
        purpose: "terms",
        label: "Terms of service",
        noticeVersion: "terms-of-service@9.9",
        recordedAt: "1 Jan 2000, 5:30 am IST",
      },
      expect.objectContaining({ purpose: "privacy_notice" }),
      expect.objectContaining({ purpose: "profile_processing" }),
      expect.objectContaining({ purpose: "analytics", label: "Product analytics" }),
    ]);
    expect(view.options.find((option) => option.purpose === "analytics")).toMatchObject({
      granted: true,
      grantedAt: "1 Jan 2000, 5:30 am IST",
    });
  });

  it("dates only a grant at the current version; an older or withdrawn one is asked again", () => {
    const summary = consentSummaryFromDto(
      summaryDto([
        grantedState("terms", "terms-of-service@9.0"),
        grantedState("whatsapp_reminders", "whatsapp-consent@9.8-draft", false),
        grantedState("analytics", "privacy-notice@9.9-draft"),
      ]),
    );
    const view = consentStepView(summary, VERSIONS, "business");
    expect(view.options.map((option) => [option.purpose, option.grantedAt])).toEqual([
      ["terms", null],
      ["privacy_notice", null],
      ["profile_processing", null],
      ["whatsapp_reminders", null],
      ["email_reminders", null],
      ["analytics", "1 Jan 2000, 5:30 am IST"],
    ]);
    expect(grantedPurposes(summary, VERSIONS)).toEqual(["analytics"]);
    expect(grantedPurposes(accepted, VERSIONS)).toEqual([
      "terms",
      "privacy_notice",
      "profile_processing",
    ]);
  });

  it("asks again when a document's version changed or a purpose was withdrawn", () => {
    const newer = {
      ...VERSIONS,
      "terms-of-service": { ...VERSIONS["terms-of-service"], version: "10.0" },
    };
    expect(hasAcceptedRequired(accepted, VERSIONS)).toBe(true);
    expect(hasAcceptedRequired(accepted, newer)).toBe(false);
    const withdrawn = consentSummaryFromDto(
      summaryDto([
        grantedState("terms", "terms-of-service@9.9"),
        grantedState("privacy_notice", "privacy-notice@9.9-draft", false),
        grantedState("profile_processing", "privacy-notice@9.9-draft"),
      ]),
    );
    expect(hasAcceptedRequired(withdrawn, VERSIONS)).toBe(false);
    // The business step's server-side check agrees with the step on every case.
    for (const [summary, versions] of [
      [accepted, VERSIONS],
      [accepted, newer],
      [withdrawn, VERSIONS],
      [empty, VERSIONS],
    ] as const) {
      expect(requiredConsentsGranted(summary, versions)).toBe(
        hasAcceptedRequired(summary, versions),
      );
    }
  });

  it("names no draft when every document is final", () => {
    const final = {
      "privacy-notice": { ...VERSIONS["privacy-notice"], isDraft: false },
      "terms-of-service": VERSIONS["terms-of-service"],
      "whatsapp-consent": { ...VERSIONS["whatsapp-consent"], isDraft: false },
    };
    expect(draftDocuments(purposesFor("business"), final)).toEqual([]);
  });
});

describe("purposesToRecord", () => {
  it("records the chosen purposes not already granted at the current version, in order", () => {
    expect(purposesToRecord(["analytics", "terms", "privacy_notice"], empty, VERSIONS)).toEqual([
      "terms",
      "privacy_notice",
      "analytics",
    ]);
    const partly = consentSummaryFromDto(
      summaryDto([grantedState("terms", "terms-of-service@9.9")]),
    );
    expect(
      purposesToRecord(["terms", "privacy_notice", "profile_processing"], partly, VERSIONS),
    ).toEqual(["privacy_notice", "profile_processing"]);
    const older = consentSummaryFromDto(
      summaryDto([grantedState("terms", "terms-of-service@9.0")]),
    );
    expect(purposesToRecord(["terms"], older, VERSIONS)).toEqual(["terms"]);
    expect(purposesToRecord(["terms"], accepted, VERSIONS)).toEqual([]);
  });
});
