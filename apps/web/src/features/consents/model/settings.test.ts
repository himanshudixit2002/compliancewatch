import { describe, expect, it } from "vitest";
import { consentSummaryFromDto } from "@/entities/consent/mappers";
import {
  ACCEPTED_STATES,
  OWNER_ID,
  VERSIONS,
  grantedState,
  recordDto,
  summaryDto,
} from "@/test/consent-fixture";
import { changeEvidence, changeStatement, consentSettingsView, sourceLabel } from "./settings";

const OWNER = { tenantKind: "business" as const, userId: OWNER_ID };

describe("consentSettingsView", () => {
  it("shows every purpose a business user is asked for as not given when nothing is recorded", () => {
    const view = consentSettingsView(consentSummaryFromDto(summaryDto()), VERSIONS, OWNER);
    expect(view.rows.map((row) => [row.purpose, row.status, row.change])).toEqual([
      ["terms", "not_given", null],
      ["privacy_notice", "not_given", null],
      ["profile_processing", "not_given", null],
      ["whatsapp_reminders", "not_given", "give"],
      ["email_reminders", "not_given", "give"],
      ["analytics", "not_given", "give"],
    ]);
    expect(view.rows[0]).toMatchObject({
      label: "Terms of service",
      required: true,
      noticeVersion: null,
      since: null,
      source: null,
      currentNoticeVersion: "terms-of-service@9.9",
      outdated: false,
      document: { name: "terms-of-service" },
    });
    expect(view.history).toEqual([]);
    expect(view.drafts.map((document) => document.name)).toEqual([
      "privacy-notice",
      "whatsapp-consent",
    ]);
    expect(view.whatsappNumber).toBe("");
  });

  it("offers to withdraw what is given, to give what was withdrawn, and flags an earlier version", () => {
    const summary = consentSummaryFromDto(
      summaryDto([
        ...ACCEPTED_STATES.slice(0, 2),
        grantedState("profile_processing", "privacy-notice@9.0"),
        grantedState("whatsapp_reminders", "whatsapp-consent@9.8-draft"),
        grantedState("analytics", "privacy-notice@9.9-draft", false),
      ]),
    );
    const view = consentSettingsView(summary, VERSIONS, {
      ...OWNER,
      whatsappNumber: "+919800000001",
    });
    const byPurpose = Object.fromEntries(view.rows.map((row) => [row.purpose, row]));
    expect(byPurpose.terms).toMatchObject({
      status: "granted",
      change: null,
      outdated: false,
      source: "Web onboarding",
      since: "1 Jan 2000, 5:30 am IST",
    });
    expect(byPurpose.profile_processing).toMatchObject({
      status: "granted",
      outdated: true,
      noticeVersion: "privacy-notice@9.0",
    });
    expect(byPurpose.whatsapp_reminders).toMatchObject({
      status: "granted",
      change: "withdraw",
      statement: "Withdraw consent: WhatsApp reminders.",
    });
    expect(byPurpose.analytics).toMatchObject({
      status: "withdrawn",
      change: "give",
      statement: "Record which screens I open and which steps I finish, to improve the app.",
    });
    expect(view.whatsappNumber).toBe("+919800000001");
  });

  it("offers a CA firm no WhatsApp box but still shows and withdraws a record on file", () => {
    const none = consentSettingsView(consentSummaryFromDto(summaryDto()), VERSIONS, {
      tenantKind: "ca_firm",
      userId: OWNER_ID,
    });
    expect(none.rows.map((row) => row.purpose)).not.toContain("whatsapp_reminders");
    const withdrawn = consentSettingsView(
      consentSummaryFromDto(
        summaryDto([grantedState("whatsapp_reminders", "whatsapp-consent@9.8-draft", false)]),
      ),
      VERSIONS,
      { tenantKind: "ca_firm", userId: OWNER_ID },
    );
    const whatsapp = withdrawn.rows.find((row) => row.purpose === "whatsapp_reminders");
    expect(whatsapp).toMatchObject({ status: "withdrawn", change: null });
    const given = consentSettingsView(
      consentSummaryFromDto(
        summaryDto([grantedState("whatsapp_reminders", "whatsapp-consent@9.8-draft")]),
      ),
      VERSIONS,
      { tenantKind: "ca_firm", userId: OWNER_ID },
    );
    expect(given.rows.find((row) => row.purpose === "whatsapp_reminders")?.change).toBe("withdraw");
  });

  it("lists every record oldest first with who recorded it", () => {
    const summary = consentSummaryFromDto(
      summaryDto(
        [],
        [
          recordDto("terms", true, "terms-of-service@9.9", { recorded_by: OWNER_ID }),
          recordDto("analytics", false, "", {
            source: "support",
            recorded_by: "00000000-0000-4000-8000-0000000000aa",
            recorded_at: "2000-01-02T00:00:00Z",
          }),
          recordDto("email_reminders", true, "privacy-notice@9.9-draft", { recorded_by: null }),
        ],
      ),
    );
    const view = consentSettingsView(summary, VERSIONS, OWNER);
    expect(
      view.history.map((item) => [item.label, item.granted, item.noticeVersion, item.recordedBy]),
    ).toEqual([
      ["Terms of service", true, "terms-of-service@9.9", "you"],
      ["Product analytics", false, null, "00000000-0000-4000-8000-0000000000aa"],
      ["Email reminders", true, "privacy-notice@9.9-draft", null],
    ]);
    expect(view.history[1]).toMatchObject({
      source: "Support",
      recordedAt: "2 Jan 2000, 5:30 am IST",
      evidence: "Example evidence",
    });
  });
});

describe("the change wording", () => {
  it("gives with the consent step's sentence and withdraws with a plain one, both as evidence", () => {
    expect(changeStatement("email_reminders", "give")).toBe(
      "Send me reminders for this business by email.",
    );
    expect(changeStatement("email_reminders", "withdraw")).toBe(
      "Withdraw consent: Email reminders.",
    );
    expect(changeEvidence("analytics", "withdraw")).toBe(
      "Confirmed on the settings page: Withdraw consent: Product analytics.",
    );
    expect(sourceLabel("whatsapp_keyword")).toBe("WhatsApp keyword");
    expect(sourceLabel("api")).toBe("API");
  });
});
