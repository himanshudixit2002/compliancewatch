import type { FlagDefinition } from "@compliancewatch/flags";
import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { flagConsoleView } from "../model/flags";
import { FlagsView } from "./flags-view";

const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.flags", href: "/admin/flags", label: "Feature flags" },
];
const TODAY = "2000-01-15";

const DEFINITIONS: FlagDefinition[] = [
  {
    name: "example.choice",
    type: "string",
    default: "first",
    values: ["first", "second"],
    owner: "platform",
    description: "Example choice between two modes.",
    removal: "When the second mode is the only one.",
    expires: "2000-01-15",
    targeting: "none",
    env: "CW_EXAMPLE_CHOICE",
    services: ["example-service", "example-worker"],
  },
  {
    name: "example.targeted",
    type: "bool",
    default: false,
    owner: "core-product",
    description: "Example switch for some tenants.",
    removal: "When every tenant has it.",
    expires: "2000-01-01",
    targeting: "tenant",
    tenants_env: "CW_EXAMPLE_TENANTS",
    services: ["example-service"],
  },
  {
    name: "example.untargeted",
    type: "bool",
    default: false,
    owner: "platform",
    description: "Example switch that targets tenants without a list variable.",
    removal: "When the example is done.",
    expires: "2000-01-30",
    targeting: "tenant",
    services: ["example-service"],
  },
  {
    name: "web.example_on",
    type: "bool",
    default: false,
    owner: "ai-platform",
    description: "Example web switch that is on.",
    removal: "When the example is done.",
    expires: "2000-12-31",
    targeting: "none",
    env: "CW_WEB_FLAG_EXAMPLE_ON",
    services: ["web"],
  },
  {
    name: "web.example_off",
    type: "bool",
    default: false,
    owner: "platform",
    description: "Example web switch that is off.",
    removal: "When the example is done.",
    expires: "2000-12-31",
    targeting: "none",
    services: ["web"],
  },
];

const VALUES = new Map([
  ["web.example_on", true],
  ["web.example_off", false],
]);

function row(container: HTMLElement, name: string): HTMLElement {
  return container.querySelector(`[data-flag='${name}']`) as HTMLElement;
}

describe("FlagsView", () => {
  it("lists every flag with its wording, default, value on the web server and expiry", async () => {
    const view = flagConsoleView(DEFINITIONS, { ok: true, provider: "env" }, VALUES, TODAY);
    const { container } = render(<FlagsView title="Feature flags" crumbs={CRUMBS} view={view} />);
    expect(screen.getByRole("heading", { level: 1, name: "Feature flags" })).toBeDefined();
    expect(
      screen.getByRole("navigation", { name: "Breadcrumb" }).querySelector("a")?.textContent,
    ).toBe("Internal tools");
    expect(container.querySelector("[data-slot='flag-provider']")?.textContent).toContain(
      "env provider",
    );
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(DEFINITIONS.length + 1);
    expect(screen.getByText("5 flags in the shared registry")).toBeDefined();

    const choice = row(container, "example.choice");
    expect(choice.textContent).toContain("Example choice between two modes.");
    expect(choice.textContent).toContain("Remove when: When the second mode is the only one.");
    expect(choice.textContent).toContain("Variable CW_EXAMPLE_CHOICE");
    expect(choice.textContent).toContain("One of its values");
    expect(choice.textContent).toContain("Values: first, second");
    expect(choice.textContent).toContain("Read by example-service, example-worker");
    expect(choice.textContent).toContain("Expires today");

    const targeted = row(container, "example.targeted");
    expect(targeted.textContent).toContain("On or off");
    expect(targeted.textContent).toContain("Allow-list of tenants: CW_EXAMPLE_TENANTS");
    expect(targeted.textContent).toContain("Expired");
    expect(row(container, "example.untargeted").textContent).toContain(
      "Can be on for some tenants",
    );
    expect(row(container, "example.untargeted").textContent).toContain("15 days left");

    const on = row(container, "web.example_on");
    expect(on.querySelector("[data-slot='status-chip']")?.textContent).toBe("On");
    expect(on.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "success",
    );
    expect(on.textContent).toContain("Off");
    expect(on.textContent).not.toContain("Expired");
    expect(
      row(container, "web.example_off").querySelector("[data-slot='status-chip']")?.textContent,
    ).toBe("Off");

    const stats = [...container.querySelectorAll("[data-slot='stat-card']")];
    expect(stats.map((card) => card.querySelector("dd")?.textContent)).toEqual([
      "5",
      "1",
      "2",
      "1",
    ]);
    expect(stats[1]?.textContent).toContain("of 2 the web app reads");
    expect(stats[2]?.getAttribute("data-tone")).toBe("warning");
    expect(stats[3]?.getAttribute("data-tone")).toBe("danger");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says why nothing was evaluated when the reader could not be configured", async () => {
    const view = flagConsoleView(
      DEFINITIONS.slice(3),
      { ok: false, reason: "Example provider without its address" },
      VALUES,
      TODAY,
    );
    const { container } = render(<FlagsView title="Feature flags" crumbs={CRUMBS} view={view} />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("could not be configured");
    expect(alert.textContent).toContain("Example provider without its address");
    expect(row(container, "web.example_on").textContent).toContain("Not evaluated");
    const stats = [...container.querySelectorAll("[data-slot='stat-card']")];
    expect(stats[2]?.getAttribute("data-tone")).toBe("neutral");
    expect(stats[3]?.getAttribute("data-tone")).toBe("neutral");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("explains an empty registry instead of an empty table", async () => {
    const view = flagConsoleView([], { ok: true, provider: "env" }, new Map(), TODAY);
    const { container } = render(<FlagsView title="Feature flags" crumbs={CRUMBS} view={view} />);
    expect(screen.getByRole("heading", { level: 2, name: "No flags registered" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
