import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { adminToolGroups } from "../model/tools";
import { AdminHomeView } from "./admin-home-view";

describe("AdminHomeView", () => {
  it("lists the tools by group with status chips, awaited routes and service README paths", async () => {
    const { container } = render(<AdminHomeView groups={adminToolGroups()} />);
    expect(screen.getByRole("heading", { level: 1, name: "Internal tools" })).toBeDefined();
    expect(screen.getAllByRole("table").length).toBe(7);
    expect(screen.getByText("Other tools")).toBeDefined();
    expect(screen.getByRole("link", { name: "Sources" }).getAttribute("href")).toBe(
      "/admin/sources",
    );
    const task = container.querySelector("[data-tool='admin.review.task']");
    expect(task?.querySelector("a")).toBeNull();
    expect(task?.textContent).toContain("services/rulebook/README.md");
    expect(task?.textContent).toContain("+");
    const flags = container.querySelector("[data-tool='admin.flags']");
    expect(flags?.textContent).toContain("file packages/flags/registry.json");
    expect(flags?.textContent).toContain("Waiting for a backend");
    expect(await runAxe(container)).toHaveNoViolations();
  }, 20_000);

  it("labels a group without a navigation placement as other tools", () => {
    render(
      <AdminHomeView
        groups={[
          {
            key: "other",
            label: null,
            tools: [
              {
                id: "admin.x",
                title: "X",
                route: "/admin/x",
                kind: "page",
                href: "/admin/x",
                roles: ["Admin"],
                status: "planned",
                waitsFor: [],
                services: [],
              },
            ],
          },
        ]}
      />,
    );
    expect(screen.getAllByText("None")).toHaveLength(2);
  });
});
