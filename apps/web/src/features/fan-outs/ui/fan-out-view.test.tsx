import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { fanOutRunFromDto } from "@/entities/applicability/mappers";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import {
  OLDER_VERSION_ID,
  RUN_VERSION_ID,
  TRIGGER_EVENT_ID,
  fanOutRunDto,
} from "@/test/engine-admin-fixture";
import { ruleVersionDetailDto } from "@/test/rule-version-fixture";
import type { FanOutPageView } from "../queries";
import { FanOutView, type FanOutViewProps } from "./fan-out-view";
import type { ControlAction } from "./use-control";

const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.fan-outs", href: "/admin/fan-outs", label: "Fan-outs" },
  { id: "admin.fan-out", href: `/admin/fan-outs/${RUN_VERSION_ID}`, label: "example_rule v2" },
];

const version = ruleVersionFromDto(
  ruleVersionDetailDto({
    rule_version_id: RUN_VERSION_ID,
    version: 2,
    status: "published",
    title: "Example rule 2",
    effective_from: "2000-01-01",
    effective_to: "2000-04-01",
    published_at: "2000-01-05T04:30:00Z",
  }),
);

function view(overrides: Partial<FanOutPageView> = {}): FanOutPageView {
  return {
    ruleVersionId: RUN_VERSION_ID,
    run: fanOutRunFromDto(
      fanOutRunDto({
        supersedes: [OLDER_VERSION_ID],
        flips_compared: 200,
        flips: 2,
        flip_rate: 0.01,
      }),
    ),
    version,
    versionFailure: null,
    hold: { ok: true, hold: { held: false, reason: null, by: null, since: null } },
    canControl: true,
    controls: ["pause", "cancel"],
    rollback: { state: "offered", access: { allowed: true } },
    ...overrides,
  };
}

function renderView(props: Partial<FanOutViewProps> = {}) {
  return render(
    <FanOutView
      title="Fan-out of example_rule v2"
      name="example_rule v2"
      crumbs={CRUMBS}
      view={view()}
      hrefs={{
        fanOut: (id) => `/admin/fan-outs/${id}`,
        version: `/admin/rulebook/versions/${RUN_VERSION_ID}`,
        dryRun: `/admin/impact?rule_version_id=${RUN_VERSION_ID}`,
      }}
      holdAction={vi.fn<ControlAction>()}
      controlAction={vi.fn<ControlAction>()}
      rollbackAction={vi.fn<ControlAction>()}
      {...props}
    />,
  );
}

describe("FanOutView", () => {
  it("shows the run, its controls and the rollback to an admin, and the version", async () => {
    const { container } = renderView();
    expect(
      screen.getByRole("heading", { level: 1, name: "Fan-out of example_rule v2" }),
    ).toBeDefined();
    const run = container.querySelector("[data-slot='run']") as HTMLElement;
    expect(run.getAttribute("data-status")).toBe("running");
    expect(within(run).getByRole("progressbar").getAttribute("aria-valuetext")).toBe(
      "1,000 of 2,000 decided",
    );
    const facts = container.querySelector("[data-slot='run-facts']") as HTMLElement;
    expect(facts.getAttribute("aria-label")).toBe("The run");
    expect(facts.textContent).toContain("2 of 200 compared flipped (1%)");
    expect(within(facts).getByRole("link", { name: OLDER_VERSION_ID }).getAttribute("href")).toBe(
      `/admin/fan-outs/${OLDER_VERSION_ID}`,
    );
    expect(facts.textContent).toContain(TRIGGER_EVENT_ID);
    expect(screen.getByRole("button", { name: "Pause" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Cancel the run" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Roll back this version" })).toBeDefined();
    const versionFacts = container.querySelector("[data-slot='version-facts']") as HTMLElement;
    expect(
      within(versionFacts).getByRole("link", { name: "example_rule v2" }).getAttribute("href"),
    ).toBe(`/admin/rulebook/versions/${RUN_VERSION_ID}`);
    expect(versionFacts.textContent).toContain("Published");
    expect(versionFacts.textContent).toContain("1 Jan 2000 to 31 Mar 2000");
    expect(
      screen
        .getByRole("link", { name: "Dry run this version in the impact explorer" })
        .getAttribute("href"),
    ).toBe(`/admin/impact?rule_version_id=${RUN_VERSION_ID}`);
    expect(await runAxe(run)).toHaveNoViolations();
  });

  it("is read-only for anyone but an admin", async () => {
    const { container } = renderView({
      view: view({ canControl: false, rollback: { state: "not_admin" } }),
      hrefs: {
        fanOut: (id) => `/admin/fan-outs/${id}`,
        version: `/admin/rulebook/versions/${RUN_VERSION_ID}`,
        dryRun: null,
      },
    });
    expect(
      screen.queryByRole("button", { name: /Pause|Resume|Cancel|Roll back|Hold|Release/ }),
    ).toBeNull();
    expect(screen.getByText("Only an admin pauses, resumes or cancels a fan-out.")).toBeDefined();
    expect(screen.getByText("Only an admin rolls a version back.")).toBeDefined();
    expect(screen.getByText("Only an admin sets or releases the hold.")).toBeDefined();
    expect(screen.queryByRole("link", { name: /Dry run/ })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says when a version has no fan-out, by its status", () => {
    const draft = ruleVersionFromDto(
      ruleVersionDetailDto({ rule_version_id: RUN_VERSION_ID, status: "draft" }),
    );
    const { rerender } = renderView({
      view: view({
        run: null,
        controls: [],
        version: draft,
        rollback: { state: "not_published", statusLabel: "Draft" },
      }),
    });
    expect(
      screen.getByRole("heading", { level: 2, name: "No fan-out for this version" }),
    ).toBeDefined();
    expect(screen.getByText(/this one is Draft\.$/)).toBeDefined();
    expect(screen.queryByRole("heading", { name: "Controls" })).toBeNull();
    rerender(
      <FanOutView
        title="Fan-out of example_rule v2"
        name="example_rule v2"
        crumbs={CRUMBS}
        view={view({ run: null, controls: [] })}
        hrefs={{ fanOut: (id) => id, version: "/v", dryRun: null }}
        holdAction={vi.fn<ControlAction>()}
        controlAction={vi.fn<ControlAction>()}
        rollbackAction={vi.fn<ControlAction>()}
      />,
    );
    expect(screen.getByText(/its worker did not handle the publication/)).toBeDefined();
    rerender(
      <FanOutView
        title="Fan-out of x"
        name="x"
        crumbs={CRUMBS}
        view={view({
          run: null,
          controls: [],
          version: null,
          rollback: { state: "unknown_version" },
        })}
        hrefs={{ fanOut: (id) => id, version: "/v", dryRun: null }}
        holdAction={vi.fn<ControlAction>()}
        controlAction={vi.fn<ControlAction>()}
        rollbackAction={vi.fn<ControlAction>()}
      />,
    );
    expect(screen.getByText(/the rulebook could not say what it is/)).toBeDefined();
    expect(screen.getByText("The rulebook does not hold this version.")).toBeDefined();
  });

  it("shows a failed run's error and a rulebook that could not be read", () => {
    const { container } = renderView({
      view: view({
        run: fanOutRunFromDto(
          fanOutRunDto({
            status: "failed",
            last_error: "Example batch failed",
            finished_at: "2000-01-05T05:00:00Z",
          }),
        ),
        controls: [],
        version: null,
        versionFailure: { message: "Example rulebook down", correlationId: "req-example-4" },
        rollback: { state: "unknown_version" },
      }),
    });
    expect(screen.getByText("Why the run failed")).toBeDefined();
    expect(screen.getByText("Example batch failed")).toBeDefined();
    expect(screen.getByText("The rulebook could not be read")).toBeDefined();
    expect(screen.getByText("req-example-4")).toBeDefined();
    expect(container.querySelector("[data-slot='run']")?.textContent).toContain("Finished");
    expect(screen.getByText(/This run has finished/)).toBeDefined();
  });
});
