import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import { EXAMPLE_VERSION_ID, ruleVersionDto } from "@/test/rule-version-fixture";
import { readListFilter } from "../model/list-filter";
import { versionRow, type VersionListView } from "../model/version-list";
import { VersionsView, type VersionsViewProps } from "./versions-view";

const PAGE = "/admin/rulebook/versions";
const TODAY = "2000-06-15";
const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.rulebook.versions", href: PAGE, label: "Rule versions" },
];

function view(
  query: Record<string, string>,
  overrides: Partial<VersionListView> = {},
): VersionListView {
  return {
    filter: readListFilter(query, TODAY).filter,
    rows: [versionRow(ruleVersionFromDto(ruleVersionDto({ high_impact: true })))],
    nextHref: null,
    firstHref: null,
    rules: [{ value: "example_rule", label: "example_rule: Example rule title" }],
    ...overrides,
  };
}

function renderView(query: Record<string, string>, props: Partial<VersionsViewProps> = {}) {
  return render(
    <VersionsView
      title="Rule versions"
      crumbs={CRUMBS}
      pageHref={PAGE}
      read={readListFilter(query, TODAY)}
      view={view(query)}
      {...props}
    />,
  );
}

describe("VersionsView", () => {
  it("lists the drafts with their status, review, period and the link to each", async () => {
    const { container } = renderView({ status: "draft" });
    expect(screen.getByRole("heading", { level: 1, name: "Rule versions" })).toBeDefined();
    const chips = screen.getByRole("navigation", { name: "Show versions by status" });
    expect(within(chips).getByRole("link", { name: "Draft" }).getAttribute("aria-current")).toBe(
      "true",
    );
    expect(within(chips).getByRole("link", { name: "In force" }).getAttribute("href")).toBe(PAGE);
    const form = screen.getByRole("form", { name: "Filter the rule versions" });
    expect(form.getAttribute("method")).toBe("get");
    expect(within(form).queryByLabelText("In force on")).toBeNull();
    expect((container.querySelector('input[name="status"]') as HTMLInputElement).value).toBe(
      "draft",
    );
    const table = screen.getByRole("table");
    expect(within(table).getByText("1 versions on this page")).toBeDefined();
    const link = within(table).getByRole("link", { name: "example_rule v1" });
    expect(link.getAttribute("href")).toBe(`/admin/rulebook/versions/${EXAMPLE_VERSION_ID}`);
    expect(within(table).getByText("Not yet reviewed")).toBeDefined();
    expect(within(table).getByText("Two different approvers")).toBeDefined();
    expect(within(table).getByText("Open questions: 1")).toBeDefined();
    expect(within(table).getByText("1 Apr 2000 to open-ended")).toBeDefined();
    expect(screen.getByText(/Versions in the status Draft for every rule/)).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("asks for the date of the in-force list and says why it is empty, with the way to the drafts", async () => {
    const { container } = renderView({}, { view: view({}, { rows: [] }) });
    expect(screen.getByLabelText("In force on")).toBeDefined();
    expect(
      screen.getByRole("heading", { name: "No version is in force on 15 Jun 2000" }),
    ).toBeDefined();
    expect(screen.getByRole("link", { name: "Show the drafts" }).getAttribute("href")).toBe(
      `${PAGE}?status=draft`,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says a status list is empty, and offers the next and the first page", () => {
    renderView(
      { status: "withdrawn", rule: "example_rule", after: "example_a" },
      {
        view: view(
          { status: "withdrawn" },
          { rows: [], nextHref: `${PAGE}?after=example_b`, firstHref: PAGE },
        ),
      },
    );
    expect(
      screen.getByRole("heading", { name: "No version in the status Withdrawn" }),
    ).toBeDefined();
    const pager = screen.getByRole("navigation", { name: "Rule version pages" });
    expect(within(pager).getByRole("link", { name: "Next page" }).getAttribute("href")).toBe(
      `${PAGE}?after=example_b`,
    );
    expect(within(pager).getByRole("link", { name: "First page" }).getAttribute("href")).toBe(PAGE);
  });

  it("marks a malformed filter on its field and reads nothing", () => {
    renderView({ as_of: "2000-99-99", rule: "Bad Key" }, { view: null });
    expect(screen.getByText("Enter a date as YYYY-MM-DD.")).toBeDefined();
    expect(screen.getByText(/This is not a rule key/)).toBeDefined();
    expect(screen.getByText("Nothing is listed until the filter is corrected.")).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("shows a failed read with its correlation id", () => {
    renderView(
      { rule: "example_rule" },
      {
        view: null,
        error: { message: "Example failure", status: 503, requestId: "req-example-1" },
      },
    );
    expect(screen.getByRole("alert").textContent).toContain("req-example-1");
    expect(screen.getByRole("option", { name: "example_rule" })).toBeDefined();
  });
});
