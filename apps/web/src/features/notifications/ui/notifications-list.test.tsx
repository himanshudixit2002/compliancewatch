import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { NotificationsList } from "./notifications-list";

const VIEW = {
  items: [
    {
      id: "ntf-1",
      subject: "GST return filed",
      channel: "email" as const,
      status: "delivered" as const,
      recipient: "owner@example.com",
      sentAt: "2024-01-15 10:30",
      readAt: "2024-01-15 11:00",
      templateKey: "gst_filed",
    },
    {
      id: "ntf-2",
      subject: "Reminder: GSTR-3B due",
      channel: "whatsapp" as const,
      status: "sent" as const,
      recipient: "+91 98765 43210",
      sentAt: "2024-01-14 09:00",
      readAt: null,
      templateKey: "gstr3b_reminder",
    },
  ],
  counts: { total: 12, sent: 8, delivered: 3, failed: 1 },
};

describe("NotificationsList", () => {
  it("renders the heading, stat cards and a table row per item", async () => {
    const { container } = render(
      <NotificationsList
        view={VIEW}
        search={{ value: "", onChange: vi.fn() }}
        baseHref="/account/notifications"
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Notifications" })).toBeDefined();
    const table = container.querySelector("[data-slot='notifications-table']") as HTMLElement;
    expect(table.textContent).toContain("GST return filed");
    expect(table.textContent).toContain("owner@example.com");
    expect(table.textContent).toContain("+91 98765 43210");
    const cells = container.querySelectorAll("[data-slot='stat-card']");
    expect(cells).toHaveLength(4);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows an empty state when the list is empty", async () => {
    const { container } = render(
      <NotificationsList
        view={{ items: [], counts: { total: 0, sent: 0, delivered: 0, failed: 0 } }}
        search={{ value: "", onChange: vi.fn() }}
        baseHref="/account/notifications"
      />,
    );
    expect(container.querySelector("[data-slot='notifications-table']")).toBeNull();
    expect(screen.getByText("No notifications yet")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
