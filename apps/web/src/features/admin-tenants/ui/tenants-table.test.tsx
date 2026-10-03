import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { TenantRow } from "./tenant-filters";
import { TenantsTable } from "./tenants-table";

function row(overrides: Partial<TenantRow>): TenantRow {
  return {
    id: "t1",
    name: "Acme Traders",
    href: "/admin/tenants/t1",
    kind: "business",
    kindLabel: "Business",
    status: "active",
    statusLabel: "Active",
    statusTone: "success",
    region: "ap-south-1",
    created: "10 Apr 2026",
    impersonateHref: "/admin/tenants/t1/impersonate",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "t1" }),
  row({
    id: "t2",
    name: "Rao & Co",
    href: null,
    kind: "ca_firm",
    kindLabel: "CA firm",
    status: "deletion_requested",
    statusLabel: "Deletion requested",
    statusTone: "warning",
    impersonateHref: null,
  }),
  row({
    id: "t3",
    name: "Regulatory team",
    href: "/admin/tenants/t3",
    kind: "internal",
    kindLabel: "Internal (regulatory team)",
    impersonateHref: null,
  }),
];

const KIND_TABS = [
  { value: "business", label: "Business" },
  { value: "ca_firm", label: "CA firm" },
  { value: "internal", label: "Internal (regulatory team)" },
];

function shownIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-tenant]")].map(
    (item) => item.getAttribute("data-tenant") ?? "",
  );
}

describe("TenantsTable", () => {
  it("lists every tenant on the All tab with its links, status and actions", async () => {
    const { container } = render(<TenantsTable rows={ROWS} kindTabs={KIND_TABS} />);
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "All",
      "Business",
      "CA firm",
      "Internal (regulatory team)",
    ]);
    expect(screen.getByRole("tab", { name: "All" }).getAttribute("aria-selected")).toBe("true");
    expect(shownIds(container)).toEqual(["t1", "t2", "t3"]);
    expect(screen.getByRole("status").textContent).toBe("Showing 3 of 3 tenants");

    const acme = container.querySelector("[data-tenant='t1']") as HTMLElement;
    expect(within(acme).getByRole("link", { name: "Acme Traders" }).getAttribute("href")).toBe(
      "/admin/tenants/t1",
    );
    expect(
      within(acme)
        .getByRole("link", { name: /^Impersonate\s*Acme Traders$/ })
        .getAttribute("href"),
    ).toBe("/admin/tenants/t1/impersonate");
    expect(acme.textContent).toContain("ap-south-1");
    expect(acme.textContent).toContain("10 Apr 2026");

    const rao = container.querySelector("[data-tenant='t2']") as HTMLElement;
    expect(within(rao).queryByRole("link")).toBeNull();
    expect(rao.textContent).toContain("CA firm");
    expect(rao.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "warning",
    );
    expect(screen.getByRole("columnheader", { name: "Actions" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("narrows by kind and search, and clears both from the no-match state", async () => {
    const user = userEvent.setup();
    const { container } = render(<TenantsTable rows={ROWS} kindTabs={KIND_TABS} />);

    await user.click(screen.getByRole("tab", { name: "CA firm" }));
    expect(shownIds(container)).toEqual(["t2"]);
    expect(screen.getByRole("status").textContent).toBe("Showing 1 of 3 tenants");

    await user.click(screen.getByRole("tab", { name: "All" }));
    await user.type(screen.getByLabelText("Search by name or ID"), "T3");
    expect(shownIds(container)).toEqual(["t3"]);

    await user.click(screen.getByRole("tab", { name: "Business" }));
    expect(shownIds(container)).toEqual([]);
    expect(screen.getByRole("heading", { level: 2, name: "No tenants found" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(screen.getByRole("button", { name: "Clear the filters" }));
    expect(shownIds(container)).toEqual(["t1", "t2", "t3"]);
    expect((screen.getByLabelText("Search by name or ID") as HTMLInputElement).value).toBe("");
    expect(screen.getByRole("tab", { name: "All" }).getAttribute("aria-selected")).toBe("true");
  });

  it("leaves out the actions column when no tenant can be impersonated", () => {
    const rows = ROWS.map((item) => ({ ...item, impersonateHref: null }));
    render(<TenantsTable rows={rows} kindTabs={KIND_TABS} />);
    expect(screen.queryByRole("columnheader", { name: "Actions" })).toBeNull();
    expect(screen.queryByRole("link", { name: /Impersonate/ })).toBeNull();
  });
});
