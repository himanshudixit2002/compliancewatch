import type { Route } from "next";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { NotificationRow } from "./notification-rows";
import { NotificationsTable } from "./notifications-table";

const ROWS: NotificationRow[] = [
  {
    id: "n1",
    subject: "GSTR-3B due on 20 Oct",
    href: "/n/n1" as Route,
    channelLabel: "WhatsApp",
    state: "sent",
    stateLabel: "Sent",
    tone: "info",
    recipient: "+919876543210",
    sentLabel: "1 Oct 2026, 10:30 am IST",
  },
];

describe("NotificationsTable", () => {
  it("renders the prepared row as given", () => {
    const { container } = render(<NotificationsTable rows={ROWS} />);
    const row = container.querySelector("[data-notification='n1']") as HTMLElement;
    expect(row.textContent).toContain("1 Oct 2026, 10:30 am IST");
    const chip = row.querySelector("[data-slot='status-chip']");
    expect(chip?.getAttribute("data-status")).toBe("sent");
    expect(chip?.getAttribute("data-tone")).toBe("info");
    expect(screen.getByRole("link", { name: "GSTR-3B due on 20 Oct" }).getAttribute("href")).toBe(
      "/n/n1",
    );
  });

  it("describes the search box and keeps what was typed", async () => {
    const user = userEvent.setup();
    render(<NotificationsTable rows={ROWS} />);
    const search = screen.getByRole("searchbox", { name: "Search notifications" });
    expect(search.getAttribute("aria-describedby")).not.toBeNull();
    await user.type(search, "sent");
    expect((search as HTMLInputElement).value).toBe("sent");
    expect(screen.getByText("Showing 1 of 1 notifications.")).toBeDefined();
  });
});
