import { describe, expect, it } from "vitest";
import { entityTypeLabel, entityTypeOptions } from "./entity-type";
import { readResolve } from "./resolve-form";

describe("readResolve", () => {
  it("asks for nothing before a type or a name is given", () => {
    expect(readResolve({})).toEqual({ kind: "empty" });
  });

  it("reads a type and a name, keeping the name as typed", () => {
    expect(readResolve({ type: "form", name: " Example Form " })).toEqual({
      kind: "ok",
      entityType: "form",
      name: " Example Form ",
    });
    expect(readResolve({ type: ["section", "rule"], name: ["Example"] })).toMatchObject({
      kind: "ok",
      entityType: "section",
    });
  });

  it("refuses an unknown type, a blank name and a name too long, keeping the values", () => {
    expect(readResolve({ type: "example", name: "  " })).toEqual({
      kind: "invalid",
      values: { type: "example", name: "  " },
      errors: { type: "Choose the entity type.", name: "Enter the name to resolve." },
    });
    expect(readResolve({ type: "form", name: "x".repeat(401) })).toMatchObject({
      kind: "invalid",
      errors: { name: "A name has at most 400 characters." },
    });
    expect(readResolve({ name: "Example" })).toMatchObject({
      kind: "invalid",
      errors: { type: "Choose the entity type." },
    });
  });
});

describe("the entity types", () => {
  it("offers every kernel type in its order, worded", () => {
    const options = entityTypeOptions();
    expect(options).toHaveLength(10);
    expect(options[0]).toEqual({ value: "notification", label: "Notification" });
    expect(entityTypeLabel("hsn_code")).toBe("HSN code");
    expect(entityTypeLabel("sac_code")).toBe("SAC code");
    expect(entityTypeLabel("tax_rate")).toBe("Tax rate");
  });
});
