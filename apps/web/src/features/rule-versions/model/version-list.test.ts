import { describe, expect, it } from "vitest";
import { ruleFromDto, ruleVersionFromDto } from "@/entities/rule-version/mappers";
import { EXAMPLE_VERSION_ID, ruleDto, ruleVersionDto } from "@/test/rule-version-fixture";
import type { VersionListFilter } from "./list-filter";
import { byRuleKey, inStatus, ruleOptions, statusChips, versionRow } from "./version-list";

const PAGE = "/admin/rulebook/versions";
const FILTER: VersionListFilter = {
  status: "draft",
  asOf: "2000-06-15",
  asOfGiven: false,
  ruleKey: "example_rule",
  after: "example_a",
};

describe("statusChips", () => {
  it("offers every status, each from the first page with the rule kept, and marks the current one", () => {
    const chips = statusChips(PAGE, FILTER);
    expect(chips.map((chip) => chip.label)).toEqual([
      "In force",
      "Draft",
      "In review",
      "Approved",
      "Published",
      "Superseded",
      "Withdrawn",
      "Every status",
    ]);
    expect(chips.filter((chip) => chip.current).map((chip) => chip.status)).toEqual(["draft"]);
    expect(chips[0]?.href).toBe(`${PAGE}?rule=example_rule`);
    expect(chips[7]?.href).toBe(`${PAGE}?status=all&rule=example_rule`);
  });
});

describe("versionRow", () => {
  it("names the version by rule key and number, with its review facts and its page", () => {
    expect(versionRow(ruleVersionFromDto(ruleVersionDto({ high_impact: true })))).toEqual({
      ruleVersionId: EXAMPLE_VERSION_ID,
      href: `/admin/rulebook/versions/${EXAMPLE_VERSION_ID}`,
      ruleKey: "example_rule",
      version: 1,
      title: "Example rule title",
      status: "draft",
      seedStatus: "needs_review",
      needsReview: true,
      effectiveFrom: "2000-04-01",
      effectiveTo: null,
      highImpact: true,
      openQuestions: 1,
      publishedAt: null,
    });
  });
});

describe("inStatus", () => {
  const versions = [
    ruleVersionFromDto(ruleVersionDto()),
    ruleVersionFromDto(ruleVersionDto({ version: 2, status: "in_review" })),
  ];

  it("keeps one status, or every version", () => {
    expect(inStatus(versions, "in_review").map((version) => version.version)).toEqual([2]);
    expect(inStatus(versions, "all")).toHaveLength(2);
    expect(inStatus(versions, "withdrawn")).toEqual([]);
  });
});

describe("ruleOptions", () => {
  it("lists the rules by key in code point order, named by their latest title", () => {
    const rules = [
      ruleFromDto(ruleDto({ rule_key: "example_b", title: "Example B" })),
      ruleFromDto(ruleDto({ rule_key: "example_a", title: "Example A" })),
      ruleFromDto(ruleDto({ rule_key: "example_a1", title: "Example A1" })),
    ];
    expect(ruleOptions(rules)).toEqual([
      { value: "example_a", label: "example_a: Example A" },
      { value: "example_a1", label: "example_a1: Example A1" },
      { value: "example_b", label: "example_b: Example B" },
    ]);
    expect(byRuleKey({ ruleKey: "a" }, { ruleKey: "a" })).toBe(0);
  });
});
