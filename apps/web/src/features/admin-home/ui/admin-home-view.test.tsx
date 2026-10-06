import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { CountTileView } from "../model/counts";
import type { ServicesSummaryView } from "../model/services";
import { adminToolGroups } from "../model/tools";
import { AdminHomeView } from "./admin-home-view";

const TILES: CountTileView[] = [
  {
    key: "entityGroups",
    title: "Entity groups to review",
    value: "200+",
    detail: "412 open mentions in these groups",
    href: "/admin/rulebook/entities",
    error: null,
  },
  {
    key: "prompts",
    title: "Prompts",
    value: null,
    detail: null,
    href: null,
    error: { message: "The service could not be reached.", requestId: "req-example-1" },
  },
];

const ALL_UP: ServicesSummaryView = { up: 10, total: 10, down: [], systemHref: null };

describe("AdminHomeView", () => {
  it("lists the tools by group with status chips, awaited routes and service README paths", async () => {
    const { container } = render(
      <AdminHomeView
        groups={adminToolGroups()}
        tiles={TILES}
        services={ALL_UP}
        probeTimeoutSeconds={2}
      />,
    );
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
    const system = container.querySelector("[data-tool='admin.system']");
    expect(system?.textContent).toContain("Available");
    expect(screen.getByRole("link", { name: "System" }).getAttribute("href")).toBe("/admin/system");
    const flags = container.querySelector("[data-tool='admin.flags']");
    expect(flags?.textContent).toContain("Available");
    const sources = container.querySelector("[data-tool='admin.sources']");
    expect(sources?.textContent).toContain("Ready to build");
    const pipeline = container.querySelector("[data-tool='admin.pipeline']");
    expect(pipeline?.textContent).toContain("Ready to build");
    const audit = container.querySelector("[data-tool='admin.audit']");
    expect(audit?.textContent).toContain("Waiting for a backend");
    // axe over every tool group is page sized and slow in jsdom on CI runners, so it checks one
    // group's table here; e2e/admin-home.spec.ts runs AxeBuilder over the whole /admin page.
    const engine = container.querySelector<HTMLElement>("[data-group='engine']");
    expect(engine).not.toBeNull();
    expect(await runAxe(engine as HTMLElement)).toHaveNoViolations();
  });

  it("shows each count, the tool it opens, and a failed count's error in its own tile", async () => {
    const { container } = render(
      <AdminHomeView groups={[]} tiles={TILES} services={ALL_UP} probeTimeoutSeconds={2} />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Queues and registries" })).toBeDefined();
    const groups = container.querySelector<HTMLElement>("[data-tile='entityGroups']");
    expect(groups?.querySelector("[data-slot='tile-value']")?.textContent).toBe("200+");
    expect(groups?.textContent).toContain("412 open mentions in these groups");
    expect(screen.getByRole("link", { name: "Entity groups to review" }).getAttribute("href")).toBe(
      "/admin/rulebook/entities",
    );
    const prompts = container.querySelector<HTMLElement>("[data-tile='prompts']");
    expect(prompts?.querySelector("[role='alert']")?.textContent).toContain(
      "The service could not be reached.",
    );
    expect(prompts?.textContent).toContain("req-example-1");
    expect(prompts?.textContent).toContain("The tool that lists these is not built yet.");
    expect(screen.getByRole("button", { name: "Refresh" })).toBeDefined();
    const tiles = container.querySelector<HTMLElement>("[data-slot='count-tiles']");
    expect(await runAxe(tiles as HTMLElement)).toHaveNoViolations();
  });

  it("names every service that does not answer, with its address and the reason", async () => {
    const { container } = render(
      <AdminHomeView
        groups={[]}
        tiles={[]}
        services={{
          up: 9,
          total: 10,
          down: [{ service: "eval", baseUrl: "http://localhost:8009", reason: "unreachable" }],
          systemHref: "/admin/system",
        }}
        probeTimeoutSeconds={2}
      />,
    );
    const summary = container.querySelector<HTMLElement>("[data-slot='services-summary']");
    expect(summary?.textContent).toContain("9 of 10 services answer their health check.");
    expect(summary?.querySelector("[data-service='eval']")?.textContent).toBe(
      "eval http://localhost:8009: unreachable",
    );
    expect(summary?.textContent).toContain("with a 2 second limit");
    expect(screen.getByRole("link", { name: "Open the system page" }).getAttribute("href")).toBe(
      "/admin/system",
    );
    expect(await runAxe(summary as HTMLElement)).toHaveNoViolations();
  });

  it("labels a group without a navigation placement as other tools", () => {
    render(
      <AdminHomeView
        tiles={[]}
        services={ALL_UP}
        probeTimeoutSeconds={2}
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
