import { describe, expect, it } from "vitest";
import { cn } from "./cn";

describe("cn", () => {
  it("joins conditional class names", () => {
    const hidden = false as boolean;
    expect(cn("a", hidden && "b", undefined, ["c", { d: true, e: false }])).toBe("a c d");
  });

  it("lets a later Tailwind utility override an earlier one in the same group", () => {
    expect(cn("px-2 py-1", "px-4")).toBe("py-1 px-4");
    expect(cn("bg-bg", "bg-surface")).toBe("bg-surface");
  });
});
