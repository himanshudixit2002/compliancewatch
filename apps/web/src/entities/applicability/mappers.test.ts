import { describe, expect, it } from "vitest";
import { changeImpactDto } from "@/test/change-fixture";
import { ENTITY_ID, REGISTRATION_ID, decisionDto } from "@/test/obligation-fixture";
import { changeImpactFromDto, decisionFromDto } from "./mappers";

describe("applicability mappers", () => {
  it("map a decision with each predicate in words", () => {
    const decision = decisionFromDto(decisionDto());
    expect(decision).toMatchObject({
      businessId: REGISTRATION_ID,
      result: "applies",
      confidence: 1,
      needsReview: false,
      trigger: "rule_published",
      asOfFy: "1999-00",
    });
    expect(decision.evaluated).toEqual([
      {
        attribute: "example_kind",
        kind: "structured",
        description: "Example kind is second",
        outcome: "applies",
        confidence: 1,
        reason: "Example kind is second on this node",
        needsReview: false,
      },
    ]);
  });

  it("group an impact's businesses under their client", () => {
    const impact = changeImpactFromDto(
      changeImpactDto([
        { result: "applies" },
        { businessId: "00000000-0000-4000-8000-0000000000a2", result: "unsure" },
      ]),
    );
    expect(impact.clients).toHaveLength(1);
    expect(impact.clients[0]?.entityId).toBe(ENTITY_ID);
    expect(impact.clients[0]?.businesses.map((business) => business.result)).toEqual([
      "applies",
      "unsure",
    ]);
    expect(impact.nextCursor).toBeNull();
  });
});
