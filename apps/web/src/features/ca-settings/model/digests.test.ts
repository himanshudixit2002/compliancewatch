import { describe, expect, it } from "vitest";
import {
  DIGEST_MODES,
  DIGEST_MODE_TONE,
  digestCounts,
  digestModeOptions,
  sortRecipients,
} from "./digests";
import type { DigestMode, DigestRecipient } from "./digests";

function recipient(id: string, name: string, mode: DigestMode): DigestRecipient {
  return {
    id,
    name,
    address: `${id}@firm.example.com`,
    mode,
    clientCount: 3,
    lastSentAt: null,
  };
}

describe("digest modes", () => {
  it("offers every mode, daily first, in words", () => {
    expect(digestModeOptions()).toEqual([
      { value: "daily", label: "Daily digest" },
      { value: "off", label: "Each change on its own" },
    ]);
    expect(DIGEST_MODES.map((mode) => DIGEST_MODE_TONE[mode])).toEqual(["info", "neutral"]);
  });
});

describe("sortRecipients", () => {
  it("orders people by name without changing the input", () => {
    const input = [
      recipient("r1", "Ravi Kumar", "daily"),
      recipient("r2", "Asha Rao", "off"),
      recipient("r3", "Meena Iyer", "daily"),
    ];
    expect(sortRecipients(input).map((person) => person.name)).toEqual([
      "Asha Rao",
      "Meena Iyer",
      "Ravi Kumar",
    ]);
    expect(input[0]?.name).toBe("Ravi Kumar");
  });
});

describe("digestCounts", () => {
  it("counts the people and those on the daily digest", () => {
    expect(
      digestCounts([
        recipient("r1", "Ravi Kumar", "daily"),
        recipient("r2", "Asha Rao", "off"),
        recipient("r3", "Meena Iyer", "daily"),
      ]),
    ).toEqual({ total: 3, daily: 2 });
    expect(digestCounts([])).toEqual({ total: 0, daily: 0 });
  });
});
