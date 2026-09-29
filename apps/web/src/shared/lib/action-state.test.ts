import { describe, expect, it } from "vitest";
import {
  actionFailure,
  actionSuccess,
  fieldErrorOf,
  fieldFailure,
  idleAction,
  type ActionState,
} from "./action-state";

describe("action state builders", () => {
  it("start idle", () => {
    expect(idleAction()).toEqual({ status: "idle" });
  });

  it("record a success with an optional value and message", () => {
    expect(actionSuccess({ id: "x" })).toEqual({ status: "ok", value: { id: "x" } });
    expect(actionSuccess(undefined, "Saved")).toEqual({
      status: "ok",
      value: undefined,
      message: "Saved",
    });
  });

  it("record a form-level failure from one message or several", () => {
    expect(actionFailure("Flag web.qa_enabled is off")).toEqual({
      status: "error",
      formErrors: ["Flag web.qa_enabled is off"],
    });
    expect(actionFailure(["a", "b"], { name: ["Required"] })).toEqual({
      status: "error",
      formErrors: ["a", "b"],
      fieldErrors: { name: ["Required"] },
    });
  });

  it("record field-only failures", () => {
    expect(fieldFailure({ gstin: ["Not a GSTIN"] })).toEqual({
      status: "error",
      fieldErrors: { gstin: ["Not a GSTIN"] },
    });
  });
});

describe("fieldErrorOf", () => {
  it("gives the first message of a field in an error state and nothing otherwise", () => {
    const state: ActionState = {
      status: "error",
      fieldErrors: { gstin: ["Not a GSTIN", "Too short"] },
    };
    expect(fieldErrorOf(state, "gstin")).toBe("Not a GSTIN");
    expect(fieldErrorOf(state, "name")).toBeUndefined();
    expect(fieldErrorOf(idleAction(), "gstin")).toBeUndefined();
    expect(fieldErrorOf(actionSuccess(), "gstin")).toBeUndefined();
  });
});
