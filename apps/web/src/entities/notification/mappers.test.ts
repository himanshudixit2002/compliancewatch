import { describe, expect, it } from "vitest";
import { preferenceChangeToDto, preferenceFromDto } from "./mappers";

describe("notification preference mappers", () => {
  it("maps the service's preference", () => {
    expect(
      preferenceFromDto({
        channel: "whatsapp",
        recipient: "+910000000000",
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
