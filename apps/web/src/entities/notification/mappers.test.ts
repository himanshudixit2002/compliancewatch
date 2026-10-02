import { describe, expect, it } from "vitest";
import {
  CHANNELS,
  emailKeyOf,
  isChannel,
  isRecipientKey,
  preferenceChangeToDto,
  preferenceFromDto,
  recipientLabel,
  templateFromDto,
  whatsappKeyOf,
  whatsappNumberOf,
} from "./mappers";

describe("notification preference mappers", () => {
  it("maps the service's preference", () => {
    expect(
      preferenceFromDto({
        channel: "whatsapp",
        recipient: "+910000000000",
        address: "+910000000000",
        opted_in: true,
        source: "web_onboarding",
        language: "en",
        quiet_hours_start: "21:00",
        quiet_hours_end: "08:00",
        updated_at: "2000-01-01T00:00:00Z",
      }),
    ).toEqual({
      channel: "whatsapp",
      recipient: "+910000000000",
      optedIn: true,
      source: "web_onboarding",
      language: "en",
      quietHoursStart: "21:00",
      quietHoursEnd: "08:00",
      updatedAt: "2000-01-01T00:00:00Z",
    });
  });

  it("sends only what is set", () => {
    expect(preferenceChangeToDto({ optedIn: true, source: "web_onboarding" })).toEqual({
      opted_in: true,
      source: "web_onboarding",
    });
    expect(
      preferenceChangeToDto({
        optedIn: false,
        source: "web_onboarding",
        language: "hi",
        quietHoursStart: "22:00",
        quietHoursEnd: "07:00",
      }),
    ).toEqual({
      opted_in: false,
      source: "web_onboarding",
      language: "hi",
      quiet_hours_start: "22:00",
      quiet_hours_end: "07:00",
    });
  });
});

describe("recipient keys", () => {
  it("names the channels in display order", () => {
    expect(CHANNELS).toEqual(["whatsapp", "email"]);
    expect(isChannel("email")).toBe(true);
    expect(isChannel("sms")).toBe(false);
  });

  it("keys a WhatsApp number by its digits and an address lowercased", () => {
    expect(whatsappKeyOf("+919800000001")).toBe("919800000001");
    expect(() => whatsappKeyOf("9800000001")).toThrow("not an E.164 number");
    expect(whatsappNumberOf("919800000001")).toBe("+919800000001");
    expect(emailKeyOf("  Owner@Example.COM ")).toBe("owner@example.com");
  });

  it("accepts only the service's own form of a key", () => {
    expect(isRecipientKey("whatsapp", "919800000001")).toBe(true);
    expect(isRecipientKey("whatsapp", "+919800000001")).toBe(false);
    expect(isRecipientKey("whatsapp", "019800000001")).toBe(false);
    expect(isRecipientKey("email", "owner@example.com")).toBe(true);
    expect(isRecipientKey("email", "Owner@example.com")).toBe(false);
    expect(isRecipientKey("email", "owner")).toBe(false);
  });

  it("shows a number with its plus and an address as it is", () => {
    expect(recipientLabel("whatsapp", "919800000001")).toBe("+919800000001");
    expect(recipientLabel("email", "owner@example.com")).toBe("owner@example.com");
  });
});

describe("templateFromDto", () => {
  it("keeps what the settings page needs and leaves the body on the service", () => {
    expect(
      templateFromDto({
        key: "example_template",
        channel: "email",
        language: "en",
        status: "draft",
        meta_name: "",
        placeholders: ["name"],
        body: "Example body {name}",
      }),
    ).toEqual({ key: "example_template", channel: "email", language: "en", status: "draft" });
  });
});
