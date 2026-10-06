import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { listedObligationFromDto } from "@/entities/obligation/mappers";
import { NOW, REGISTRATION_ID, dueAt, listedObligationDto } from "@/test/obligation-fixture";
import { encodeListKey, obligationRow, readListFilter } from "../model/list";
import { statusFilterOptions } from "../model/obligations";
import type { ObligationListView } from "../queries";
import { ObligationsView } from "./obligations-view";

const HEADER = {
  crumbs: [
    { id: "owner.businesses", href: "/businesses", label: "Businesses" },
    { id: "owner.business", href: "/b/x", label: "Example business" },
    { id: "owner.obligations", href: "/b/x/obligations", label: "Obligations" },
  ],
  tabs: [
    { id: "owner.business", href: "/b/x", label: "Business" },
    { id: "owner.obligations", href: "/b/x/obligations", label: "Obligations" },
  ],
};

const NODES = [
  { id: "00000000-0000-4000-8000-0000000000e1", name: "Example business (PAN ABCDE1234F)" },
  { id: REGISTRATION_ID, name: "29ABCDE1234F1Z5 (Example registration)" },
];

function view(overrides: Partial<ObligationListView> = {}): ObligationListView {
  const items = [
    listedObligationDto({ due_at: dueAt("2000-01-09") }),
    listedObligationDto({
      obligation_id: "00000000-0000-4000-8000-0000000000b2",
      title: "Example return 2",
      status: "done",
      rule_version: null,
      citations: [],
    }),
  ].map(listedObligationFromDto);
  return {
    business: { id: "x", name: "Example business", pan: "ABCDE1234F" },
    nodes: 2,
    read: readListFilter({}),
    rows: items.map((item) =>
      obligationRow(item, { href: `/b/x/obligations/${item.id}`, nodes: NODES, now: NOW }),
    ),
    asked: true,
    nextHref: "/b/x/obligations?after=abc",
    firstHref: null,
    ...overrides,
  };
}

function renderView(model: ObligationListView, severalNodes = true) {
  return render(
    <ObligationsView
      title="Obligations"
      view={model}
      header={HEADER}
      pageHref="/b/x/obligations"
      statusOptions={statusFilterOptions()}
      severalNodes={severalNodes}
    />,
  );
}

describe("ObligationsView", () => {
  it("lists the obligations with their status, due date, node and review state", async () => {
    const { container } = renderView(view());
    expect(screen.getByRole("heading", { level: 1, name: "Obligations" })).toBeDefined();
    const table = screen.getByRole("table");
    const first = within(table).getByRole("link", { name: "Example return 1" });
    expect(first.getAttribute("href")).toBe(
      "/b/x/obligations/00000000-0000-4000-8000-0000000000b1",
    );
    const row = container.querySelector(
      "tr[data-obligation='00000000-0000-4000-8000-0000000000b1']",
    );
    expect(row?.textContent).toContain("Overdue by 1 day");
    expect(row?.textContent).toContain("29ABCDE1234F1Z5 (Example registration)");
    expect(row?.textContent).toContain("Not yet reviewed");
    expect(row?.textContent).toContain("1 verified citation");
    const done = container.querySelector(
      "tr[data-obligation='00000000-0000-4000-8000-0000000000b2']",
    );
    expect(done?.textContent).toContain("Review not known yet");
    expect(done?.textContent).toContain("0 verified citations");
    expect(screen.getByRole("link", { name: "Next page" }).getAttribute("href")).toBe(
      "/b/x/obligations?after=abc",
    );
    expect(screen.getByRole("complementary", { name: "Not legal advice" })).toBeDefined();
    expect(screen.getByText(/at most 366 days/)).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("leaves the node out for a business with one", () => {
    const { container } = renderView(view(), false);
    expect(container.textContent).not.toContain("(Example registration)");
  });

  it("says why the list is empty: nothing yet, nothing matching, or the end of the list", () => {
    const empty = renderView(view({ rows: [], nextHref: null }));
    expect(screen.getByRole("heading", { level: 2, name: "No obligations yet" })).toBeDefined();
    empty.unmount();
    const filtered = renderView(
      view({
        rows: [],
        nextHref: null,
        read: readListFilter({ status: "done", from: "2000-01-01" }),
      }),
    );
    expect(screen.getByRole("heading", { level: 2, name: "No obligations match" })).toBeDefined();
    expect(screen.getByText(/Due on or after 1 Jan 2000/)).toBeDefined();
    filtered.unmount();
    const statusOnly = renderView(
      view({ rows: [], nextHref: null, read: readListFilter({ status: "done" }) }),
    );
    expect(screen.getByText(/Choose another status, or clear the filters/)).toBeDefined();
    statusOnly.unmount();
    renderView(
      view({
        rows: [],
        nextHref: null,
        firstHref: "/b/x/obligations",
        read: readListFilter({
          after: encodeListKey({ dueAt: null, id: "00000000-0000-4000-8000-00000000000a" }),
        }),
      }),
    );
    expect(screen.getByRole("heading", { level: 2, name: "No more obligations" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Back to the first page" })).toBeDefined();
  });

  it("shows a refused window on its field and lists nothing for it", async () => {
    const { container } = renderView(
      view({
        rows: [],
        asked: false,
        nextHref: null,
        read: readListFilter({ from: "2000-01-01", to: "2001-06-30" }),
      }),
    );
    expect(
      screen.getByRole("heading", { level: 2, name: "Nothing listed for this window" }),
    ).toBeDefined();
    expect(screen.getByText(/This window spans 547 days/)).toBeDefined();
    const to = screen.getByLabelText(/Due by/) as HTMLInputElement;
    expect(to.value).toBe("2001-06-30");
    expect(to.getAttribute("aria-invalid")).toBe("true");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
