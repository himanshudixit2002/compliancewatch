import { describe, expect, it } from "vitest";
import { entityDecisionLabel, type EntityGroupDecision, type RejectReason } from "./types";

describe("entityDecisionLabel", () => {
  it("returns a label for each decision kind", () => {
    expect(entityDecisionLabel("create_entity")).toBe("Create entity");
    expect(entityDecisionLabel("add_alias")).toBe("Add alias");
    expect(entityDecisionLabel("reject")).toBe("Reject");
  });

  it("returns a fallback for an unknown kind", () => {
    expect(entityDecisionLabel("unknown")).toBe("Submit");
  });
});

describe("EntityGroupDecision", () => {
  it("create_entity carries no extra fields", () => {
    const d: EntityGroupDecision = { kind: "create_entity" };
    expect(d.kind).toBe("create_entity");
  });

  it("reject carries a reason", () => {
    const d: EntityGroupDecision = { kind: "reject", reason: "not_an_entity" };
    expect(d.kind).toBe("reject");
  });

  it("add_alias carries no extra fields", () => {
    const d: EntityGroupDecision = { kind: "add_alias" };
    expect(d.kind).toBe("add_alias");
  });
});

describe("RejectReason", () => {
  it("accepts all valid values", () => {
    const reasons = ["not_an_entity", "wrong_type", "text_artifact", "out_of_scope"] as const;
    for (const reason of reasons) {
      const d: EntityGroupDecision = { kind: "reject", reason };
      expect(d.kind).toBe("reject");
    }
  });
});
