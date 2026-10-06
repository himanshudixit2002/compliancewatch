import { describe, expect, it } from "vitest";
import { REVIEWED_TENANT_ID, RUN_VERSION_ID } from "@/test/engine-admin-fixture";
import { DRY_RUN_FIELDS, type DryRunFormValues } from "../ui/dry-run-shared";
import { formValues, initialValues, parseDryRunForm, parseSpecification } from "./form";

const VERSION: DryRunFormValues = {
  subject: "version",
  ruleVersionId: ` ${RUN_VERSION_ID.toUpperCase()} `,
  specification: "",
  level: "",
  tenantId: "",
  sampleSize: "10",
};

describe("the dry run form", () => {
  it("reads what was sent, and starts with a version named by the address", () => {
    const data = new FormData();
    data.set(DRY_RUN_FIELDS.subject, "specification");
    data.set(DRY_RUN_FIELDS.specification, "{}");
    data.set(DRY_RUN_FIELDS.level, "nonsense");
    expect(formValues(data)).toEqual({
      subject: "specification",
      ruleVersionId: "",
      specification: "{}",
      level: "",
      tenantId: "",
      sampleSize: "",
    });
    expect(initialValues(RUN_VERSION_ID)).toMatchObject({
      subject: "version",
      ruleVersionId: RUN_VERSION_ID,
      sampleSize: "10",
    });
    expect(initialValues(null).ruleVersionId).toBe("");
  });

  it("asks for a version by its id, every tenant unless one is named", () => {
    expect(parseDryRunForm(VERSION)).toEqual({
      ok: true,
      request: {
        ruleVersionId: RUN_VERSION_ID,
        specification: null,
        level: null,
        tenantId: null,
        sampleSize: 10,
      },
    });
    expect(
      parseDryRunForm({
        ...VERSION,
        tenantId: REVIEWED_TENANT_ID.toUpperCase(),
        level: "entity",
        sampleSize: "0",
      }),
    ).toMatchObject({
      ok: true,
      request: { tenantId: REVIEWED_TENANT_ID, level: "entity", sampleSize: 0 },
    });
  });

  it("asks for a specification as a JSON object with the level it is decided at", () => {
    const spec = { attribute: "example_kind", operator: "eq", value: "first" };
    expect(
      parseDryRunForm({
        ...VERSION,
        subject: "specification",
        specification: JSON.stringify(spec),
        level: "registration",
      }),
    ).toMatchObject({
      ok: true,
      request: { ruleVersionId: null, specification: spec, level: "registration" },
    });
  });

  it("refuses each field it cannot send, on that field", () => {
    expect(
      parseDryRunForm({ ...VERSION, ruleVersionId: "x", tenantId: "y", sampleSize: "51" }),
    ).toEqual({
      ok: false,
      fieldErrors: {
        rule_version_id: ["Enter the rule version's id."],
        "scope.tenant_id": ["Enter the tenant's id, a UUID, or leave it empty for every tenant."],
        "scope.sample_size": ["Enter a whole number from 0 to 50."],
      },
    });
    expect(
      parseDryRunForm({
        ...VERSION,
        subject: "specification",
        specification: "[1]",
        sampleSize: "two",
      }),
    ).toEqual({
      ok: false,
      fieldErrors: {
        specification: ["Enter the specification as a JSON object of at most 20000 characters."],
        "scope.level": ["Choose the level the specification is decided at."],
        "scope.sample_size": ["Enter a whole number from 0 to 50."],
      },
    });
    expect(
      parseDryRunForm({
        ...VERSION,
        subject: "specification",
        specification: `{"a":"${"x".repeat(20001)}"}`,
        level: "entity",
      }).ok,
    ).toBe(false);
  });

  it("reads only a JSON object as a specification", () => {
    expect(parseSpecification('{"all_of": []}')).toEqual({ all_of: [] });
    expect(parseSpecification("null")).toBeNull();
    expect(parseSpecification("[]")).toBeNull();
    expect(parseSpecification("{")).toBeNull();
  });
});
