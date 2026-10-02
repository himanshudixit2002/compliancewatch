import { describe, expect, it } from "vitest";
import { consentSummaryFromDto } from "@/entities/consent/mappers";
import { preferenceFromDto, templateFromDto } from "@/entities/notification/mappers";
import { grantedState, summaryDto } from "@/test/consent-fixture";
import { EMAIL_KEY, TEMPLATE_DTOS, WHATSAPP_KEY, preferenceDto } from "@/test/notification-fixture";
import { notificationSettingsView } from "./view";

const TEMPLATES = TEMPLATE_DTOS.map(templateFromDto);
const NO_CONSENTS = consentSummaryFromDto(summaryDto());

describe("notificationSettingsView", () => {
  it("asks for a recipient on each channel when this device remembers none", () => {
    const view = notificationSettingsView({
      recipients: {},
      preferences: {},
      templates: TEMPLATES,
      consents: NO_CONSENTS,
    });
    expect(view.channels.map((channel) => [channel.channel, channel.state.kind])).toEqual([
      ["whatsapp", "no_recipient"],
      ["email", "no_recipient"],
    ]);
    expect(view.channels[0]).toMatchObject({
      title: "WhatsApp",
      purpose: "whatsapp_reminders",
      purposeLabel: "WhatsApp reminders",
      consentGiven: false,
      recipient: null,
      recipientField: "WhatsApp number",
      form: { optedIn: false, language: "en", quietHoursStart: "21:00", quietHoursEnd: "08:00" },
    });
    expect(view.channels[0]?.languages.map((option) => option.value)).toEqual(["en", "hi"]);
  });

  it("shows a recorded preference, a recipient with nothing recorded, and a failed read", () => {
    const consents = consentSummaryFromDto(
      summaryDto([grantedState("whatsapp_reminders", "whatsapp-consent@9.8-draft")]),
    );
    const view = notificationSettingsView({
      recipients: { whatsapp: WHATSAPP_KEY, email: EMAIL_KEY },
      preferences: {
        whatsapp: {
          ok: true,
          value: preferenceFromDto(
            preferenceDto({
              language: "hi",
              quiet_hours_start: "22:00",
              quiet_hours_end: "07:00",
              source: "whatsapp_keyword",
            }),
          ),
        },
        email: { ok: true, value: null },
      },
      templates: TEMPLATES,
      consents,
    });
    const [whatsapp, email] = view.channels;
    expect(whatsapp).toMatchObject({
      consentGiven: true,
      recipient: "+910000000000",
      state: {
        kind: "recorded",
        preference: {
          optedIn: true,
          statusLabel: "Opted in",
          languageLabel: "Hindi",
          quietHours: "22:00 to 07:00 IST, across midnight",
          source: "WhatsApp keyword",
          updatedAt: "1 Jan 2000, 5:30 am IST",
        },
      },
      form: { optedIn: true, language: "hi", quietHoursStart: "22:00", quietHoursEnd: "07:00" },
    });
    expect(email).toMatchObject({
      consentGiven: false,
      recipient: EMAIL_KEY,
      state: { kind: "not_recorded" },
      form: { optedIn: false },
    });
    const failed = notificationSettingsView({
      recipients: { email: EMAIL_KEY },
      preferences: { email: { ok: false, error: { message: "Down", requestId: "req-1" } } },
      templates: TEMPLATES,
      consents,
    });
    expect(failed.channels[1]?.state).toEqual({
      kind: "error",
      error: { message: "Down", requestId: "req-1" },
    });
  });

  it("starts the form opted in for a new recipient when the consent is given", () => {
    const view = notificationSettingsView({
      recipients: { email: EMAIL_KEY },
      preferences: {},
      templates: TEMPLATES,
      consents: consentSummaryFromDto(
        summaryDto([grantedState("email_reminders", "privacy-notice@9.9-draft")]),
      ),
    });
    expect(view.channels[1]).toMatchObject({
      state: { kind: "not_recorded" },
      form: { optedIn: true, language: "en" },
    });
  });
});
