import { describe, expect, it } from "vitest";
import { ruleFromDto } from "@/entities/rule-version/mappers";
import { EXAMPLE_RULE_ID, ruleDto } from "@/test/rule-version-fixture";
import { filterRules } from "../ui/rules-shared";
import { ruleRows } from "./rules";

const rows = ruleRows([
  ruleFromDto(ruleDto({ rule_key: "example_second", title: "Example quarterly return" })),
  ruleFromDto(ruleDto()),
]);

describe("ruleRows", () => {
  it("lists the rules by key, each linking every version it has", () => {
    expect(rows).toEqual([
      {
        ruleKey: "example_rule",
        ruleId: EXAMPLE_RULE_ID,
        regulator: "example_regulator",
        title: "Example rule title",
        versionsHref: "/admin/rulebook/versions?status=all&rule=example_rule",
      },
      {
        ruleKey: "example_second",
        ruleId: EXAMPLE_RULE_ID,
        regulator: "example_regulator",
        title: "Example quarterly return",
        versionsHref: "/admin/rulebook/versions?status=all&rule=example_second",
      },
    ]);
  });
});

describe("filterRules", () => {
  it("keeps the rows holding every word, in any case, in the key, title or regulator", () => {
    expect(filterRules(rows, "").map((row) => row.ruleKey)).toEqual([
      "example_rule",
      "example_second",
    ]);
    expect(filterRules(rows, "  QUARTERLY ").map((row) => row.ruleKey)).toEqual(["example_second"]);
    expect(filterRules(rows, "example_rule title").map((row) => row.ruleKey)).toEqual([
      "example_rule",
    ]);
    expect(filterRules(rows, "example_regulator monthly")).toEqual([]);
  });
});
