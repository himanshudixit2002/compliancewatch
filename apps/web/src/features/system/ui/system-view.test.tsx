import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { serviceRow, type HealthLike, type ReadyLike } from "../model/system";
import type { WebFacts } from "./system-shared";
import { SystemView } from "./system-view";

const crumbs = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.system", href: "/admin/system", label: "System" },
];

const FACTS: WebFacts = {
  environment: "test",
  authProvider: null,
  build: null,
  requestTimeoutMs: 10000,
  writeToken: true,
  reviewToken: false,
  flagProvider: { ok: true, name: "env" },
  telemetry: { enabled: true, exporting: false },
  node: "v0.0.0",
};

function health(service: string, overrides: Partial<HealthLike> = {}): HealthLike {
  return {
    service,
    baseUrl: "http://localhost:9000",
    state: "up",
    version: "0.0.1",
    latencyMs: 4,
    ...overrides,
  };
}

function ready(service: string, overrides: Partial<ReadyLike> = {}): ReadyLike {
  return { service, state: "ready", checks: { database: true }, latencyMs: 2, ...overrides };
}

describe("SystemView", () => {
  it("shows each service's health and readiness, the registry's view and this server's facts", async () => {
    const rows = [
      serviceRow(health("rulebook"), ready("rulebook")),
      serviceRow(
        health("eval", { state: "down", reason: "unreachable", version: undefined }),
        ready("eval", { state: "down", checks: {} }),
      ),
    ];
    const { container } = render(
      <SystemView
        title="System"
        crumbs={crumbs}
        rows={rows}
        summary={{ total: 2, up: 1, ready: 1 }}
        facts={FACTS}
        probeTimeoutSeconds={2}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "System" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeDefined();
    expect(screen.getByText("Services that do not answer their health check: 1")).toBeDefined();
    const rulebook = container.querySelector("[data-service='rulebook']");
    expect(rulebook?.textContent).toContain("Version 0.0.1");
    expect(rulebook?.textContent).toContain("database: passed");
    expect(container.querySelector("[data-service='eval']")?.textContent).toContain("unreachable");
    expect(container.querySelector("[data-registry='rulebook']")?.textContent).toMatch(
      /Screens: \d+/,
    );
    const facts = container.querySelector("[data-slot='web-facts']");
    expect(facts?.textContent).toContain("Not configured");
    expect(facts?.textContent).toContain("Development build");
    expect(facts?.textContent).toContain(
      "On, with no exporter configured: spans stay in this server",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("raises no alarm when every service answers, and words a failed flag provider", () => {
    render(
      <SystemView
        title="System"
        crumbs={crumbs}
        rows={[serviceRow(health("qa"), ready("qa"))]}
        summary={{ total: 1, up: 1, ready: 1 }}
        facts={{
          ...FACTS,
          flagProvider: { ok: false, reason: "Example reason" },
          telemetry: { enabled: false, exporting: false },
          build: "abc123",
          authProvider: "fake",
        }}
        probeTimeoutSeconds={2}
      />,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Not configured: Example reason")).toBeDefined();
    expect(screen.getByText("Off (web.otel_enabled)")).toBeDefined();
    expect(screen.getByText("abc123")).toBeDefined();
  });

  it("says how OpenTelemetry registered at startup: exporting, failed, or not recorded", () => {
    const view = (telemetry: WebFacts["telemetry"]) => (
      <SystemView
        title="System"
        crumbs={crumbs}
        rows={[serviceRow(health("qa"), ready("qa"))]}
        summary={{ total: 1, up: 1, ready: 1 }}
        facts={{ ...FACTS, telemetry }}
        probeTimeoutSeconds={2}
      />
    );
    const { container, rerender } = render(view({ enabled: true, exporting: true }));
    const facts = () => container.querySelector("[data-slot='web-facts']")?.textContent ?? "";
    expect(facts()).toContain("OpenTelemetry, as it registered when this server started");
    expect(facts()).toContain("On, exporting over OTLP");
    rerender(view({ enabled: false, exporting: false, failed: true }));
    expect(facts()).toContain("Off: registration failed at startup");
    rerender(view(null));
    expect(facts()).toContain("Not known: no registration was recorded in this server process");
  });
});
