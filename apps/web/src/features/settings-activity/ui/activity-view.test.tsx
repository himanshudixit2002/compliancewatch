import { render, screen, within } from "@testing-library/react";
import type { Route } from "next";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import type { ActivityEntry } from "../model/activity";
import { ActivityView } from "./activity-view";

const CRUMBS = [
  { id: "owner.settings", href: "/settings", label: "Settings" },
  { id: "owner.settings.activity", href: "/settings/activity", label: "Activity" },
];
const TABS = [
  { id: "owner.settings.consents", href: "/settings/consents", label: "Consents" },
  { id: "owner.settings.activity", href: "/settings/activity", label: "Activity" },
];

const ENTRIES: ActivityEntry[] = [
  {
    id: "ev_1",
    actor: "Example owner",
    action: "consent_withdrawn",
    subject: "WhatsApp reminders",
    at: "2000-09-30T10:00:00Z",
  },
  {
    id: "ev_2",
    actor: null,
    action: "obligation.rescheduled",
    subject: "Example return 1 for September 2000",
    at: "2000-10-02T03:30:00Z",
  },
  {
    id: "ev_3",
    actor: "Example owner",
    action: "role_changed",
    subject: "Example staff member",
    at: "2000-10-01T08:15:00Z",
  },
];

describe("ActivityView", () => {
  it("shows the trail newest first: when, who, what happened and what it applied to", async () => {
    const { container } = render(
      <ActivityView title="Activity" entries={ENTRIES} crumbs={CRUMBS} tabs={TABS} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Activity" })).toBeDefined();
    expect(screen.getByRole("navigation", { name: "Settings pages" })).toBeDefined();
    expect(screen.getByText("Changes in this account, newest first")).toBeDefined();
    const rows = [...container.querySelectorAll<HTMLElement>("tbody tr")];
    expect(rows.map((tr) => tr.getAttribute("data-activity"))).toEqual(["ev_2", "ev_3", "ev_1"]);
    expect(
      within(rows[0]!)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual([
      formatDateTime("2000-10-02T03:30:00Z"),
      "ComplianceWatch (automatic)",
      "Obligation rescheduled",
      "Example return 1 for September 2000",
    ]);
    expect(
      within(rows[2]!)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual([
      formatDateTime("2000-09-30T10:00:00Z"),
      "Example owner",
      "Consent withdrawn",
      "WhatsApp reminders",
    ]);
    expect(within(rows[0]!).getAllByRole("cell")[1]?.className).toContain("text-fg-muted");
    expect(screen.queryByRole("link", { name: "Older activity" })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("links to older entries when there are more", () => {
    render(
      <ActivityView
        title="Activity"
        entries={ENTRIES}
        crumbs={CRUMBS}
        tabs={TABS}
        olderHref={"/settings/activity?after=ev_1" as Route}
      />,
    );
    expect(screen.getByRole("link", { name: "Older activity" }).getAttribute("href")).toBe(
      "/settings/activity?after=ev_1",
    );
  });

  it("explains an empty trail instead of an empty table", async () => {
    const { container } = render(
      <ActivityView title="Activity" entries={[]} crumbs={CRUMBS} tabs={TABS} />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No activity yet" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
