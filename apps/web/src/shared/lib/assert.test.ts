import { describe, expect, it } from "vitest";
import { AssertionError, assert, assertNever, unwrap } from "./assert.ts";

describe("assert", () => {
  it("throws an AssertionError with the message when the condition fails", () => {
    expect(() => assert(false, "must hold")).toThrow(AssertionError);
    expect(() => assert(0, "zero")).toThrow("zero");
    expect(() => assert(true, "fine")).not.toThrow();
  });

  it("unwraps present values and names missing ones", () => {
    expect(unwrap("x", "value")).toBe("x");
    expect(() => unwrap(null, "session")).toThrow("session");
    expect(() => unwrap(undefined, "session")).toThrow(AssertionError);
  });

  it("reports the unexpected value in assertNever", () => {
    expect(() => assertNever("oops" as never)).toThrow('unexpected value: "oops"');
    expect(() => assertNever(1 as never, "status")).toThrow("status: 1");
  });
});
