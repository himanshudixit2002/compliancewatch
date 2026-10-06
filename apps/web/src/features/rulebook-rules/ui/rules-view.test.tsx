import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { ruleFromDto } from "@/entities/rule-version/mappers";
import { ruleDto } from "@/test/rule-version-fixture";
import { ruleRows } from "../model/rules";
import { RulesView } from "./rules-view";

const crumbs = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.rulebook.rules", href: "/admin/rulebook/rules", label: "Rules" },
];

const rows = ruleRows([
  ruleFromDto(ruleDto()),
  ruleFromDto(ruleDto({ rule_key: "example_second", title: "Example quarterly return" })),
]);

describe("RulesView", () => {
  it("lists every rule with a link to its versions and filters them as words are typed", async () => {
    const { container } = render(<RulesView title="Rules" crumbs={crumbs} rows={rows} />);
    expect(screen.getByRole("heading", { level: 1, name: "Rules" })).toBeDefined();
    expect(screen.getByText("2 of 2 rules shown.")).toBeDefined();
    expect(
      screen.getByRole("link", { name: "Every version of example_rule" }).getAttribute("href"),
    ).toBe("/admin/rulebook/versions?status=all&rule=example_rule");
    expect(await runAxe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/^Filter the rules/), "quarterly");
    expect(screen.getByText("1 of 2 rules shown.")).toBeDefined();
    expect(container.querySelectorAll("tbody tr")).toHaveLength(1);
    await user.clear(screen.getByLabelText(/^Filter the rules/));
    await user.type(screen.getByLabelText(/^Filter the rules/), "nothing like it");
    expect(screen.getByText("No rule matches every word typed.")).toBeDefined();
    expect(container.querySelector("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says why the list is empty", () => {
    render(<RulesView title="Rules" crumbs={crumbs} rows={[]} />);
    expect(screen.getByRole("heading", { name: "The rulebook holds no rule yet" })).toBeDefined();
  });
});
