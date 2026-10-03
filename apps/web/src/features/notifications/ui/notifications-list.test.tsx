import type { Route } from "next";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import type { NotificationSummary } from "../model/notifications";
import { NotificationsList } from "./notifications-list";

const ITEMS: NotificationSummary[] = [
  {
    id: "ntf-1",
    subject: "Example return filed",
    channel: "email",
    state: "delivered",
    recipient: "owner@example.com",
    templateKey: "example_filed",
    sentAt: "2000-10-01T05:00:00Z",
  },
  {
    id: "ntf-2",
    subject: "Reminder: example return due",
    channel: "whatsapp",
    state: "queued",
    recipient: "+910000000001",
    templateKey: "example_reminder",
    sentAt: null,
  },
  {
    id: "ntf-3",
    subject: "Example payment overdue",
    channel: "whatsapp",
    state: "failed",
    recipient: "+910000000002",
    templateKey: "example_overdue",
    sentAt: "2000-09-30T05:00:00Z",
  },
];

const hrefFor = (id: string) => `/account/notifications/${id}` as Route;

function figures(container: HTMLElement): Record<string, string | null> {
  const cards = [...container.querySelectorAll<HTMLElement>("[data-slot='stat-card']")];
  return Object.fromEntries(
    cards.map((card) => [card.querySelector("dt")?.textContent, card.getAttribute("data-tone")]),
  );
}

describe("NotificationsList", () => {
  it("shows the figures and a row per notification linking to its detail", async () => {
    const { container } = render(<NotificationsList items={ITEMS} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { level: 1, name: "Notifications" })).toBeDefined();
    const values = [...container.querySelectorAll("[data-slot='stat-card'] dd")].map(
      (node) => node.textContent,
    );
    expect(values).toEqual(["3", "1", "1", "1"]);
    expect(figures(container)["Not delivered"]).toBe("danger");

    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(screen.getByRole("link", { name: "Example return filed" }).getAttribute("href")).toBe(
      "/account/notifications/ntf-1",
    );
    const queued = container.querySelector("[data-notification='ntf-2']") as HTMLElement;
    expect(queued.textContent).toContain("Not sent yet");
    expect(queued.textContent).toContain("Queued");
    expect(queued.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "neutral",
    );
    const sent = container.querySelector("[data-notification='ntf-1']") as HTMLElement;
    expect(sent.textContent).toContain(formatDateTime("2000-10-01T05:00:00Z"));
    expect(sent.textContent).toContain("Email");
    expect(screen.getByText("Showing 3 of 3 notifications.")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("narrows the table as you search and says when nothing matches", async () => {
    const user = userEvent.setup();
    const { container } = render(<NotificationsList items={ITEMS} hrefFor={hrefFor} />);
    const search = screen.getByRole("searchbox", { name: "Search notifications" });

    await user.type(search, "whatsapp");
    expect(screen.getByText("Showing 2 of 3 notifications.")).toBeDefined();
    expect(screen.queryByRole("link", { name: "Example return filed" })).toBeNull();

    await user.clear(search);
    await user.type(search, "  no such text ");
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("heading", { name: "No notification matches" })).toBeDefined();
    expect(screen.getByText('Nothing matches "no such text". Try a shorter search.')).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();

    await user.clear(search);
    expect(screen.getByText("Showing 3 of 3 notifications.")).toBeDefined();
  });

  it("shows an empty state and no search box when nothing was sent", async () => {
    const { container } = render(<NotificationsList items={[]} hrefFor={hrefFor} />);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "No notifications yet" })).toBeDefined();
    expect(figures(container)["Not delivered"]).toBe("neutral");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
