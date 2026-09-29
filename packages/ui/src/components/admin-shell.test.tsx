import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { AdminShell } from "./admin-shell";

const groups = [
  { label: "Rulebook", items: [{ href: "/admin/rulebook", label: "Documents", active: true }] },
  { label: "System", items: [{ href: "/admin/system", label: "System" }] },
];

describe("AdminShell", () => {
  it("shows the internal banner with the environment and the grouped tools", async () => {
    const { container } = render(
      <AdminShell groups={groups} environment="local" userMenu={<span>me</span>}>
        <h1>Tool</h1>
      </AdminShell>,
    );
    const banner = screen.getByRole("status");
    expect(banner.textContent).toContain("Internal tools");
    expect(within(banner).getByText("local").dataset.slot).toBe("environment");
    const nav = screen.getByRole("navigation", { name: "Internal tools" });
    expect(within(nav).getByText("Rulebook")).toBeDefined();
    expect(within(nav).getByRole("link", { name: "Documents" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(screen.getByRole("link", { name: /ComplianceWatch/ }).getAttribute("href")).toBe(
      "/admin",
    );
    expect(screen.getByRole("main").id).toBe("main");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("opens the tools sheet on small screens", async () => {
    render(
      <AdminShell groups={groups} environment="test">
        <p>Body</p>
      </AdminShell>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Open internal tools" }));
    const sheet = screen.getByRole("dialog", { name: "Internal tools" });
    expect(within(sheet).getByRole("link", { name: "System" }).getAttribute("href")).toBe(
      "/admin/system",
    );
  });
});
