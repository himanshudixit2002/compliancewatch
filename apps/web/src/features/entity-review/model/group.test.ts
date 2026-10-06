import { describe, expect, it } from "vitest";
import { entityDecidedFromDto, reviewItemFromDto } from "@/entities/rulebook/mappers";
import { EXAMPLE_ENTITY_ID, groupDecisionDto, reviewItemDto } from "@/test/rulebook-fixture";
import { canName, decisionResult, groupView, itemRows, readGroup } from "./group";
import { reviewReasonLabel } from "./labels";

describe("readGroup", () => {
  it("names no group without a type and a name", () => {
    expect(readGroup({})).toEqual({ kind: "none" });
    expect(readGroup({ type: " " })).toEqual({ kind: "none" });
  });

  it("reads a type and a name, an empty name included", () => {
    expect(readGroup({ type: "form", name: "EXAMPLE-1" })).toEqual({
      kind: "ok",
      entityType: "form",
      name: "EXAMPLE-1",
    });
    expect(readGroup({ type: "form" })).toEqual({ kind: "ok", entityType: "form", name: "" });
    expect(readGroup({ type: ["notification"], name: ["01/2000-example"] })).toEqual({
      kind: "ok",
      entityType: "notification",
      name: "01/2000-example",
    });
  });

  it("refuses a name without a type, an unknown type and a name that is too long", () => {
    expect(readGroup({ name: "EXAMPLE-1" })).toEqual({
      kind: "invalid",
      message: "The address has a name but no entity type.",
    });
    expect(readGroup({ type: "example", name: "x" })).toEqual({
      kind: "invalid",
      message: '"example" is not an entity type the rulebook knows.',
    });
    expect(readGroup({ type: "form", name: "x".repeat(401) })).toMatchObject({ kind: "invalid" });
  });
});

describe("canName", () => {
  it("takes a name, and a section or rule only with its statute", () => {
    expect(canName("form", "EXAMPLE-1")).toBe(true);
    expect(canName("form", "")).toBe(false);
    expect(canName("section", "16(2)")).toBe(false);
    expect(canName("section", "16(2)@example-act")).toBe(true);
    expect(canName("rule", "36(4)")).toBe(false);
  });
});

describe("groupView", () => {
  it("lists the mentions with links and asks the resolve tool about the name", () => {
    const view = groupView("form", "EXAMPLE-1", [reviewItemFromDto(reviewItemDto())]);
    expect(view).toMatchObject({
      typeLabel: "Form",
      nameLabel: "EXAMPLE-1",
      resolveHref: "/admin/rulebook/entities/canonical?type=form&name=EXAMPLE-1",
      queueHref: "/admin/rulebook/entities?type=form",
      nameable: true,
    });
    expect(view.items).toEqual(itemRows([reviewItemFromDto(reviewItemDto())]));
    expect(view.items[0]?.documentHref).toContain("clause_id=");
  });

  it("has nothing to resolve for an empty name", () => {
    const view = groupView("form", "", []);
    expect(view.resolveHref).toBeNull();
    expect(view.nameLabel).toBe("(no name)");
    expect(view.nameable).toBe(false);
  });
});

describe("decisionResult", () => {
  it("says how many mentions closed and links the entity made", () => {
    expect(decisionResult(entityDecidedFromDto(groupDecisionDto()))).toEqual({
      message: "Decision recorded. Mentions closed: 2.",
      statusLabel: "Resolved",
      resolutionLabel: "A new entity was made",
      entityId: EXAMPLE_ENTITY_ID,
      entityHref: `/admin/rulebook/entities/canonical/${EXAMPLE_ENTITY_ID}`,
      itemsClosed: 2,
      relationTargetsUpdated: 1,
    });
  });

  it("words a rejection without an entity, and a resolution it does not know as sent", () => {
    const rejected = decisionResult(
      entityDecidedFromDto(
        groupDecisionDto({ status: "rejected", resolution: null, entity_id: null }),
      ),
    );
    expect(rejected).toMatchObject({ resolutionLabel: null, entityId: null, entityHref: null });
    expect(
      decisionResult(entityDecidedFromDto(groupDecisionDto({ resolution: "example_way" })))
        .resolutionLabel,
    ).toBe("Example way");
  });
});

describe("reviewReasonLabel", () => {
  it("words the rulebook's reasons and keeps one it does not know", () => {
    expect(reviewReasonLabel("ambiguous_alias")).toBe("Several entities share this name");
    expect(reviewReasonLabel("unqualified")).toBe("A section or rule without its statute");
    expect(reviewReasonLabel("example_reason")).toBe("Example reason");
  });
});
