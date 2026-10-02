import { describe, expect, it } from "vitest";
import { WHATSAPP_NUMBER_FIELD, normalisePhone, parseConsentForm, whatsappRecipient } from "./form";

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

const REQUIRED = { terms: "on", privacy_notice: "on", profile_processing: "on" };

describe("parseConsentForm", () => {
  it("takes the ticked purposes in the order they are asked", () => {
    expect(
      parseConsentForm(form({ analytics: "on", ...REQUIRED }), { offerWhatsapp: true }),
    ).toEqual({
      ok: true,
      value: {
        purposes: ["terms", "privacy_notice", "profile_processing", "analytics"],
        whatsappNumber: null,
      },
    });
  });

  it("names each required box left unticked", () => {
    expect(parseConsentForm(form({ terms: "on" }), { offerWhatsapp: true })).toEqual({
      ok: false,
      fieldErrors: {
        privacy_notice: ["Tick this box to continue."],
        profile_processing: ["Tick this box to continue."],
      },
    });
  });

  it("takes a required purpose already granted at the current version as given", () => {
    expect(
      parseConsentForm(form({ terms: "on" }), {
        offerWhatsapp: true,
        granted: ["privacy_notice", "profile_processing", "analytics"],
      }),
    ).toEqual({ ok: true, value: { purposes: ["terms"], whatsappNumber: null } });
  });

  it("needs an E.164 number with the WhatsApp box and normalises it", () => {
    const ok = parseConsentForm(
      form({
        ...REQUIRED,
        whatsapp_reminders: "on",
        [WHATSAPP_NUMBER_FIELD]: "+91 (98) 000-00000",
      }),
      { offerWhatsapp: true },
    );
    expect(ok).toEqual({
      ok: true,
      value: {
        purposes: ["terms", "privacy_notice", "profile_processing", "whatsapp_reminders"],
        whatsappNumber: "+919800000000",
      },
    });
    expect(
      parseConsentForm(form({ ...REQUIRED, whatsapp_reminders: "on" }), { offerWhatsapp: true }),
    ).toEqual({
      ok: false,
      fieldErrors: { [WHATSAPP_NUMBER_FIELD]: ["Enter the WhatsApp number the reminders go to."] },
    });
    expect(
      parseConsentForm(form({ ...REQUIRED, whatsapp_reminders: "on", whatsapp_number: "98000" }), {
        offerWhatsapp: true,
      }),
    ).toEqual({
      ok: false,
      fieldErrors: {
        [WHATSAPP_NUMBER_FIELD]: ["Enter the number with its country code, starting with +."],
      },
    });
  });

  it("ignores a number without the box, and refuses the box where it is not offered", () => {
    expect(
      parseConsentForm(form({ ...REQUIRED, whatsapp_number: "+919800000000" }), {
        offerWhatsapp: true,
      }),
    ).toMatchObject({ ok: true, value: { whatsappNumber: null } });
    expect(
      parseConsentForm(form({ ...REQUIRED, whatsapp_reminders: "on" }), { offerWhatsapp: false }),
    ).toEqual({
      ok: false,
      fieldErrors: {
        whatsapp_reminders: [
          "WhatsApp reminders are set for each client business, not for the firm.",
        ],
      },
    });
  });
});

describe("normalisePhone", () => {
  it("drops spaces, dashes, dots and brackets", () => {
    expect(normalisePhone(" +91 (98)-00.00 ")).toBe("+91980000");
    expect(whatsappRecipient("+919800000000")).toBe("919800000000");
    expect(whatsappRecipient("919800000000")).toBe("919800000000");
  });
});
