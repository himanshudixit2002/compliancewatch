import { describe, expect, it } from "vitest";
import { actionLabel, actorLabel, newestFirst } from "./activity";
import type { ActivityEntry } from "./activity";

function entry(id: string, at: string): ActivityEntry {
  return { id, actor: "Asha Rao", action: "role_changed", subject: "Ravi Kumar", at };
}

describe("actionLabel", () => {
  it("reads the trail's action as a sentence, whichever separator it uses", () => {
    expect(actionLabel("consent_withdrawn")).toBe("Consent withdrawn");
    expect(actionLabel("consent.withdrawn")).toBe("Consent withdrawn");
    expect(actionLabel("api_key.created")).toBe("API key created");
  });
});

describe("actorLabel", () => {
  it("names the person, or the service for an automatic change", () => {
    expect(actorLabel("Asha Rao")).toBe("Asha Rao");
    expect(actorLabel(null)).toBe("ComplianceWatch (automatic)");
  });
});

describe("newestFirst", () => {
  it("orders by instant, not by text, newest first, keeping ties in order and the input as it was", () => {
    const input = [
      entry("a", "2026-09-30T10:00:00Z"),
      // 06:30 UTC: earlier than c and d, though its text sorts after theirs.
      entry("b", "2026-10-01T12:00:00+05:30"),
      entry("c", "2026-10-01T08:00:00Z"),
      entry("d", "2026-10-01T08:00:00Z"),
    ];
    expect(newestFirst(input).map((item) => item.id)).toEqual(["c", "d", "b", "a"]);
    expect(input[0]?.id).toBe("a");
  });
});
