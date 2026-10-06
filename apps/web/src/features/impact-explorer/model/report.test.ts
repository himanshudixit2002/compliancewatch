import { describe, expect, it } from "vitest";
import { dryRunReportFromDto } from "@/entities/applicability/mappers";
import { REVIEWED_TENANT_ID, dryRunOutDto } from "@/test/engine-admin-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import { dryRunView } from "./report";

describe("a dry run's report in words", () => {
  it("counts each result with its share, names the attributes, and lists the samples", () => {
    const view = dryRunView(dryRunReportFromDto(dryRunOutDto()), ontologyFixture());
    expect(view.subject).toBe("example_rule (Draft)");
    expect(view.scope).toBe("Every tenant's businesses");
    expect(view.level).toBe("Registrations (GSTIN)");
    expect(view.nothingInScope).toBe(false);
    expect(view.facts).toEqual({ inScope: "3", evaluated: "3", skipped: "0", max: "2,000" });
    expect(view.counts.map((count) => [count.key, count.value, count.share])).toEqual([
      ["applies", "1", "33% of those decided"],
      ["not_applicable", "1", "33% of those decided"],
      ["unsure", "1", "33% of those decided"],
      ["needs_review", "1", "33% of those decided"],
    ]);
    expect(view.byAttribute[0]).toMatchObject({ attribute: "example_kind", applies: "1" });
    expect(view.byAttribute[0]?.definition).not.toBeNull();
    expect(view.byAttribute[1]?.definition).toBeNull();
    expect(view.samples[0]).toMatchObject({
      tenantId: REVIEWED_TENANT_ID,
      result: "applies",
      confidence: "100%",
      deciding: ["example_kind"],
    });
    expect(view.samples[0]?.conditions[0]?.description).toBe("Example kind is second");
  });

  it("says a specification, one tenant, nothing in scope, and keys alone without the ontology", () => {
    const view = dryRunView(
      dryRunReportFromDto(
        dryRunOutDto({
          rule_version_id: null,
          rule_key: null,
          status: null,
          tenant_id: REVIEWED_TENANT_ID,
          businesses_total: 0,
          evaluated: 0,
          counts: { applies: 0, not_applicable: 0, unsure: 0 },
          needs_review: 0,
        }),
      ),
      null,
    );
    expect(view.subject).toBe("A specification no version holds");
    expect(view.scope).toBe(`The businesses of tenant ${REVIEWED_TENANT_ID}`);
    expect(view.nothingInScope).toBe(true);
    expect(view.counts[0]?.share).toBeNull();
    expect(view.byAttribute[0]?.definition).toBeNull();
  });
});
