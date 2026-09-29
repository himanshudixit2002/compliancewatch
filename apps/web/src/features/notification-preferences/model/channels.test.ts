import { describe, expect, it } from "vitest";
import { CHANNEL_PURPOSE, channelLabel, parseRecipient, recipientFieldLabel } from "./channels";

describe("channels", () => {
  it("names each channel, its field and the consent that backs an opt-in", () => {
    expect(CHANNEL_PURPOSE).toEqual({ whatsapp: "whatsapp_reminders", email: "email_reminders" });
    expect(channelLabel("whatsapp")).toBe("WhatsApp");
    expect(recipientFieldLabel("email")).toBe("Email address");
  });

  it("keys a typed WhatsApp number by its digits, or says what is wrong", () => {
    expect(parseRecipient("whatsapp", "+91 00000-00000")).toEqual({
      ok: true,
      key: "910000000000",
    });
    expect(parseRecipient("whatsapp", " ")).toEqual({
      ok: false,
      error: "Enter the WhatsApp number the reminders go to.",
    });
    expect(parseRecipient("whatsapp", "0000000000")).toEqual({
      ok: false,
      error: "Enter the number with its country code, starting with +.",
    });
  });

  it("keys a typed address lowercased, or says what is wrong", () => {
    expect(parseRecipient("email", " Owner@Example.com ")).toEqual({
      ok: true,
      key: "owner@example.com",
    });
    expect(parseRecipient("email", "")).toEqual({
      ok: false,
      error: "Enter the address the reminders go to.",
    });
    expect(parseRecipient("email", "owner")).toEqual({
      ok: false,
      error: "Enter an email address, such as name@example.com.",
    });
  });
});
