import { describe, expect, it } from "vitest";
import { describedBy, fieldIds } from "./ids";

describe("describedBy", () => {
  it("joins the present ids with spaces", () => {
    expect(describedBy("a", undefined, "b", false, null, "")).toBe("a b");
  });

  it("is undefined when nothing describes the control", () => {
    expect(describedBy(undefined, false)).toBeUndefined();
  });
});

describe("fieldIds", () => {
  it("derives the description and error ids", () => {
    expect(fieldIds("gstin")).toEqual({
      control: "gstin",
      description: "gstin-description",
      error: "gstin-error",
    });
  });
});
