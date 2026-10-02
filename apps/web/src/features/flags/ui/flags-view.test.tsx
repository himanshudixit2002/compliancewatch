import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { FLAG_NAMES } from "@/shared/config/flags";
import type { FlagName } from "@/shared/config/flags";
import { flagViews } from "../model/flags";
import type { FlagView } from "../model/flags";
import { FlagsView } from "./flags-view";

const ALL_OFF = Object.fromEntries(FLAG_NAMES.map((name) => [name, false])) as Record<
  FlagName,
  boolean
>;

function row(container: HTMLElement, name: FlagName): HTMLElement {
  return container.querySelector(`[data-flag='${name}']`) as HTMLElement;
}

describe("FlagsView", () => {
  it("lists every web flag with its registry wording, state and expiry", async () => {
    const flags = flagViews({ ...ALL_OFF, "web.qa_enabled": true });
    const { container } = render(
      <FlagsView title="Feature flags" flags={flags} today="2026-10-02" />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Feature flags" })).toBeDefined();
    expect(
      screen.getByText(`${FLAG_NAMES.length} web flags from the shared registry`),
    ).toBeDefined();
    expect(screen.getAllByRole("row")).toHaveLength(FLAG_NAMES.length + 1);

    const qa = row(container, "web.qa_enabled");
    expect(qa.textContent).toContain("The web app's ask screen on the qa ask route.");
    expect(qa.textContent).toContain("Override CW_WEB_FLAG_QA_ENABLED");
    expect(qa.textContent).toContain("Remove when: When the qa ask route is on for every tenant.");
    expect(qa.textContent).toContain("ai-platform");
    expect(qa.textContent).toContain("31 Mar 2027");
    expect(qa.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "success",
    );
    expect(qa.textContent).toContain("On");
    expect(qa.textContent).not.toContain("Expired");

    const otel = row(container, "web.otel_enabled");
    expect(otel.querySelector("[data-slot='status-chip']")?.textContent).toBe("Off");

    const stats = container.querySelectorAll("[data-slot='stat-card']");
    expect([...stats].map((card) => card.textContent)).toEqual([
      `Web flags${FLAG_NAMES.length}`,
      "On1",
      "Past their expiry date0",
    ]);
    expect(stats[2]?.getAttribute("data-tone")).toBe("neutral");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("marks a flag past its expiry date", () => {
    const flags = flagViews(ALL_OFF).map((flag): FlagView =>
      flag.name === "web.otel_enabled" ? { ...flag, expires: "2026-01-31" } : flag,
    );
    const { container } = render(
      <FlagsView title="Feature flags" flags={flags} today="2026-10-02" />,
    );
    expect(row(container, "web.otel_enabled").textContent).toContain("Expired");
    expect(row(container, "web.qa_enabled").textContent).not.toContain("Expired");
    const stats = container.querySelectorAll("[data-slot='stat-card']");
    expect(stats[2]?.textContent).toBe("Past their expiry date1");
    expect(stats[2]?.getAttribute("data-tone")).toBe("danger");
  });

  it("says so when the registry declares no web flags", async () => {
    const { container } = render(<FlagsView title="Feature flags" flags={[]} today="2026-10-02" />);
    expect(screen.getByRole("heading", { level: 2, name: "No web flags" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
