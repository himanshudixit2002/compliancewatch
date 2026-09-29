import { describe, expect, it } from "vitest";
import {
  PREFERENCE_FIELDS,
  parsePreferenceForm,
  parseRecipientForm,
  readChannel,
} from "./preference-form";

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

const VALID = {
  channel: "whatsapp",
  opted_in: "in",
  language: "hi",
  quiet_hours_start: "22:00",
  quiet_hours_end: "07:00",
};

describe("parseRecipientForm", () => {
  it("takes the channel and the typed recipient, and refuses an unknown channel", () => {
    expect(parseRecipientForm(form({ channel: "email", recipient: " a@example.com " }))).toEqual({
      ok: true,
      value: { channel: "email", recipient: "a@example.com" },
    });
    expect(parseRecipientForm(form({ channel: "sms", recipient: "x" }))).toEqual({
      ok: false,
      formErrors: ["Choose WhatsApp or email."],
    });
    expect(readChannel(form({}))).toBeNull();
  });
});

describe("parsePreferenceForm", () => {
  it("reads the choice, the offered language and both ends of the quiet hours", () => {
    expect(parsePreferenceForm(form(VALID), ["en", "hi"])).toEqual({
      ok: true,
      value: {
        channel: "whatsapp",
        optedIn: true,
        language: "hi",
        quietHoursStart: "22:00",
        quietHoursEnd: "07:00",
      },
    });
    expect(parsePreferenceForm(form({ ...VALID, opted_in: "out" }), ["en", "hi"])).toMatchObject({
      ok: true,
      value: { optedIn: false },
    });
  });

  it("names every field that is wrong", () => {
    expect(
      parsePreferenceForm(
        form({
          channel: "whatsapp",
          opted_in: "maybe",
          language: "fr",
          quiet_hours_start: "9pm",
          quiet_hours_end: "",
        }),
        ["en"],
      ),
    ).toEqual({
      ok: false,
      fieldErrors: {
        [PREFERENCE_FIELDS.optedIn]: ["Choose whether to send reminders."],
        [PREFERENCE_FIELDS.language]: ["Choose one of the languages listed."],
        [PREFERENCE_FIELDS.quietStart]: ["Enter a time as HH:MM on the 24-hour clock."],
        [PREFERENCE_FIELDS.quietEnd]: ["Enter a time as HH:MM on the 24-hour clock."],
      },
    });
    expect(parsePreferenceForm(form({ ...VALID, channel: "" }), ["en"])).toEqual({
      ok: false,
      formErrors: ["Choose WhatsApp or email."],
    });
  });
});
