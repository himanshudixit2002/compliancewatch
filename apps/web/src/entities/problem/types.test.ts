import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { SERVICES_WITH_SPECS } from "@/shared/config/services";

// The Problem type is taken from the identity spec's generated types; this test is what lets
// it stand for every service: the seven committed specs must publish the same schemas.
const SPEC_DIR = resolve(__dirname, "../../../../../packages/contracts/openapi");

interface OpenApiDocument {
  components: { schemas: Record<string, unknown> };
}

function schemasOf(service: string): Record<string, unknown> {
  const file = join(SPEC_DIR, `${service}.v1.json`);
  return (JSON.parse(readFileSync(file, "utf8")) as OpenApiDocument).components.schemas;
}

describe("the Problem schema", () => {
  const reference = schemasOf("identity");

  it("is identical in every committed spec, as is ValidationIssue", () => {
    expect(SERVICES_WITH_SPECS.length).toBeGreaterThan(1);
    for (const service of SERVICES_WITH_SPECS) {
      const schemas = schemasOf(service);
      expect(schemas.Problem, `${service} Problem`).toEqual(reference.Problem);
      expect(schemas.ValidationIssue, `${service} ValidationIssue`).toEqual(
        reference.ValidationIssue,
      );
    }
  });

  it("requires type, title and status and leaves the rest optional", () => {
    const problem = reference.Problem as {
      required: string[];
      properties: Record<string, unknown>;
    };
    expect([...problem.required].sort()).toEqual(["status", "title", "type"]);
    expect(Object.keys(problem.properties).sort()).toEqual([
      "correlation_id",
      "detail",
      "errors",
      "instance",
      "status",
      "title",
      "type",
    ]);
    const issue = reference.ValidationIssue as { required: string[] };
    expect([...issue.required].sort()).toEqual(["loc", "msg", "type"]);
  });
});
