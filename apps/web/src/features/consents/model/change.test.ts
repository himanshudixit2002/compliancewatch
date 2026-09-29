import { describe, expect, it } from "vitest";
import { consentSummaryFromDto } from "@/entities/consent/mappers";
import { OWNER_ID, VERSIONS, grantedState, summaryDto } from "@/test/consent-fixture";
import { CHANGE_FIELDS, consentChangeRecord, parseConsentChange } from "./change";

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

const BUSINESS = { offerWhatsapp: true };

describe("parseConsentChange", () => {
  it("accepts an optional purpose with give or withdraw", () => {
    expect(
      parseConsentChange(form({ purpose: "analytics", change: "withdraw" }), BUSINESS),
    ).toEqual({
      ok: true,
      value: { purpose: "analytics", change: "withdraw", whatsappNumber: null },
    });
    expect(
      parseConsentChange(
        form({ purpose: "email_reminders", change: "give", whatsapp_number: "+919800000001" }),
        BUSINESS,
      ),
    ).toEqual({
      ok: true,
      value: { purpose: "email_reminders", change: "give", whatsappNumber: null },
    });
  });

  it("refuses a required purpose, an unknown one and an unknown change", () => {
    expect(parseConsentChange(form({ purpose: "terms", change: "withdraw" }), BUSINESS)).toEqual({
      ok: false,
      formErrors: ["This consent is not changed on this page."],
    });
    expect(parseConsentChange(form({ change: "give" }), BUSINESS).ok).toBe(false);
    expect(parseConsentChange(form({ purpose: "analytics", change: "edit" }), BUSINESS)).toEqual({
      ok: false,
      formErrors: ["Choose to give or to withdraw the consent."],
    });
  });

  it("needs the number to give WhatsApp reminders, normalised to E.164", () => {
    const give = { purpose: "whatsapp_reminders", change: "give" };
    expect(parseConsentChange(form(give), BUSINESS)).toEqual({
      ok: false,
      fieldErrors: {
        [CHANGE_FIELDS.number]: ["Enter the WhatsApp number the reminders go to."],
      },
    });
    expect(parseConsentChange(form({ ...give, whatsapp_number: "98000 00001" }), BUSINESS)).toEqual(
      {
        ok: false,
        fieldErrors: {
          [CHANGE_FIELDS.number]: ["Enter the number with its country code, starting with +."],
        },
      },
    );
    expect(
      parseConsentChange(form({ ...give, whatsapp_number: "+91 98000-00001" }), BUSINESS),
    ).toEqual({
      ok: true,
      value: { purpose: "whatsapp_reminders", change: "give", whatsappNumber: "+919800000001" },
    });
    expect(
      parseConsentChange(form({ ...give, whatsapp_number: "+919800000001" }), {
        offerWhatsapp: false,
      }),
    ).toEqual({
      ok: false,
      formErrors: ["WhatsApp reminders are set for each client business, not for the firm."],
    });
  });

  it("withdraws WhatsApp reminders with or without a number", () => {
    const withdraw = { purpose: "whatsapp_reminders", change: "withdraw" };
    expect(parseConsentChange(form(withdraw), { offerWhatsapp: false })).toEqual({
      ok: true,
      value: { purpose: "whatsapp_reminders", change: "withdraw", whatsappNumber: null },
    });
    expect(
      parseConsentChange(form({ ...withdraw, whatsapp_number: "+919800000001" }), BUSINESS),
    ).toMatchObject({ ok: true, value: { whatsappNumber: "+919800000001" } });
  });
});

describe("consentChangeRecord", () => {
  const given = consentSummaryFromDto(
    summaryDto([grantedState("whatsapp_reminders", "whatsapp-consent@9.0")]),
  );
  const none = consentSummaryFromDto(summaryDto());

  it("withdraws with the notice version of the grant it withdraws", () => {
    expect(
      consentChangeRecord(
        { purpose: "whatsapp_reminders", change: "withdraw", whatsappNumber: null },
        given,
        VERSIONS,
        OWNER_ID,
      ),
    ).toEqual({
      subject: OWNER_ID,
      purpose: "whatsapp_reminders",
      granted: false,
      source: "web_settings",
      noticeVersion: "whatsapp-consent@9.0",
      evidence: "Confirmed on the settings page: Withdraw consent: WhatsApp reminders.",
      recordedBy: OWNER_ID,
    });
  });

  it("gives at the current version with the checkbox sentence", () => {
    expect(
      consentChangeRecord(
        { purpose: "whatsapp_reminders", change: "give", whatsappNumber: "+919800000001" },
        given,
        VERSIONS,
        OWNER_ID,
      ),
    ).toMatchObject({
      granted: true,
      noticeVersion: "whatsapp-consent@9.8-draft",
      evidence:
        "Confirmed on the settings page: Send me GST reminders for this business on WhatsApp. I can reply STOP at any time.",
    });
  });

  it("records nothing when the change is already the current state", () => {
    expect(
      consentChangeRecord(
        { purpose: "analytics", change: "withdraw", whatsappNumber: null },
        none,
        VERSIONS,
        OWNER_ID,
      ),
    ).toBeNull();
    const current = consentSummaryFromDto(
      summaryDto([grantedState("analytics", "privacy-notice@9.9-draft")]),
    );
    expect(
      consentChangeRecord(
        { purpose: "analytics", change: "give", whatsappNumber: null },
        current,
        VERSIONS,
        OWNER_ID,
      ),
    ).toBeNull();
  });
});
