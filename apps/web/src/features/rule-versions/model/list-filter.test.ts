import { describe, expect, it } from "vitest";
import { isRuleKey, listHref, readListFilter } from "./list-filter";

const TODAY = "2000-06-15";
const PAGE = "/admin/rulebook/versions";

describe("readListFilter", () => {
  it("reads the in-force list for today with every rule by default", () => {
    expect(readListFilter({}, TODAY)).toEqual({
      filter: { status: "in_force", asOf: TODAY, asOfGiven: false, ruleKey: null, after: null },
      invalid: {},
    });
  });

  it("reads a status, a date, a rule and a cursor", () => {
    expect(
      readListFilter(
        { status: "draft", as_of: "2000-01-31", rule: "example_rule", after: "example_a" },
        TODAY,
      ).filter,
    ).toEqual({
      status: "draft",
      asOf: "2000-01-31",
      asOfGiven: true,
      ruleKey: "example_rule",
      after: "example_a",
    });
  });

  it("takes the first of repeated values and falls back to the default for an unknown status", () => {
    const read = readListFilter({ status: ["example", "draft"], rule: [" example_rule "] }, TODAY);
    expect(read.filter.status).toBe("in_force");
    expect(read.filter.ruleKey).toBe("example_rule");
  });

  it("refuses a malformed date and rule key, keeping what was typed", () => {
    const read = readListFilter({ as_of: "2000-13-45", rule: "Example Rule" }, TODAY);
    expect(read.invalid).toEqual({ asOf: "2000-13-45", rule: "Example Rule" });
    expect(read.filter.asOf).toBe(TODAY);
    expect(read.filter.ruleKey).toBeNull();
  });

  it("ignores a malformed cursor and starts from the first page", () => {
    expect(readListFilter({ after: "Not a key" }, TODAY).filter.after).toBeNull();
    expect(isRuleKey("example_rule_1")).toBe(true);
    expect(isRuleKey("1example")).toBe(false);
  });
});

describe("listHref", () => {
  const base = { status: "in_force", asOf: TODAY, asOfGiven: false, ruleKey: null } as const;

  it("leaves the default status and today's date out", () => {
    expect(listHref(PAGE, base)).toBe(PAGE);
  });

  it("keeps a chosen date for the in-force list only, the rule and the cursor", () => {
    expect(listHref(PAGE, { ...base, asOf: "2000-01-31", asOfGiven: true }, "example_a")).toBe(
      `${PAGE}?as_of=2000-01-31&after=example_a`,
    );
    expect(
      listHref(PAGE, {
        ...base,
        status: "draft",
        asOf: "2000-01-31",
        asOfGiven: true,
        ruleKey: "example_rule",
      }),
    ).toBe(`${PAGE}?status=draft&rule=example_rule`);
  });
});
