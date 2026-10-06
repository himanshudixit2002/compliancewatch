import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { fanOutRunFromDto } from "@/entities/applicability/mappers";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import { OLDER_VERSION_ID, RUN_VERSION_ID, fanOutRunDto } from "@/test/engine-admin-fixture";
import { ruleVersionDto } from "@/test/rule-version-fixture";
import { fanOutRow } from "../model/fan-outs";
import type { FanOutListView } from "../queries";
import { FanOutsView } from "./fan-outs-view";
import type { ControlAction } from "./use-control";

const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.fan-outs", href: "/admin/fan-outs", label: "Fan-outs" },
];

function view(overrides: Partial<FanOutListView> = {}): FanOutListView {
  return {
    hold: { ok: true, hold: { held: false, reason: null, by: null, since: null } },
    rows: [
      fanOutRow(
        fanOutRunFromDto(fanOutRunDto()),
        ruleVersionFromDto(ruleVersionDto({ rule_version_id: RUN_VERSION_ID, version: 2 })),
        `/admin/fan-outs/${RUN_VERSION_ID}`,
      ),
      fanOutRow(
        fanOutRunFromDto(
          fanOutRunDto({
            rule_version_id: OLDER_VERSION_ID,
            status: "paused",
            status_reason: "Example flips past the threshold",
            finished_at: null,
          }),
        ),
        null,
        `/admin/fan-outs/${OLDER_VERSION_ID}`,
      ),
    ],
    canControl: false,
    nextHref: "/admin/fan-outs?cursor=next-1",
    firstHref: null,
    ...overrides,
  };
}

describe("FanOutsView", () => {
  it("lists the runs under the hold, each opening its version's page", async () => {
    const { container } = render(
      <FanOutsView
        title="Fan-outs"
        crumbs={CRUMBS}
        view={view()}
        holdAction={vi.fn<ControlAction>()}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Fan-outs" })).toBeDefined();
    expect(screen.getByText("No hold is set: fan-outs run as rules are published.")).toBeDefined();
    const table = screen.getByRole("table");
    expect(within(table).getByText("2 fan-outs on this page, newest first")).toBeDefined();
    const running = container.querySelector(`[data-fan-out='${RUN_VERSION_ID}']`) as HTMLElement;
    expect(
      within(running).getByRole("link", { name: "example_rule v2" }).getAttribute("href"),
    ).toBe(`/admin/fan-outs/${RUN_VERSION_ID}`);
    expect(running.textContent).toContain("Running");
    expect(running.textContent).toContain("1,000 of 2,000 decided");
    expect(running.textContent).toContain("Applies to 400");
    const paused = container.querySelector(`[data-fan-out='${OLDER_VERSION_ID}']`) as HTMLElement;
    expect(paused.textContent).toContain("Paused");
    expect(paused.textContent).toContain("Example flips past the threshold");
    expect(screen.getByRole("link", { name: "Older fan-outs" }).getAttribute("href")).toBe(
      "/admin/fan-outs?cursor=next-1",
    );
    expect(await runAxe(table)).toHaveNoViolations();
  });

  it("says no fan-out has run before any version is published, and the end of a later page", async () => {
    const { container, rerender } = render(
      <FanOutsView
        title="Fan-outs"
        crumbs={CRUMBS}
        view={view({ rows: [], nextHref: null })}
        holdAction={vi.fn<ControlAction>()}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No fan-out has run yet" })).toBeDefined();
    expect(screen.queryByRole("navigation", { name: "Pages of the fan-outs" })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
    rerender(
      <FanOutsView
        title="Fan-outs"
        crumbs={CRUMBS}
        view={view({ rows: [], nextHref: null, firstHref: "/admin/fan-outs" })}
        holdAction={vi.fn<ControlAction>()}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No more fan-outs" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Back to the newest" }).getAttribute("href")).toBe(
      "/admin/fan-outs",
    );
  });
});
