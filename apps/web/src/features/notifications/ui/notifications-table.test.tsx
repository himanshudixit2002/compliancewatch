import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { notificationFromDto } from "@/entities/notification/mappers";
import { formatDateTime } from "@/shared/lib/dates";
import { NOTIFICATION_ID, notificationDto } from "@/test/notification-fixture";
import { notificationRows } from "../model/notifications";
import { NotificationsTable } from "./notifications-table";

describe("NotificationsTable", () => {
  it("names each notification by its template and shows where it went and how far it got", async () => {
    const rows = notificationRows(
      [
        notificationFromDto(notificationDto({ template_key: "example_due_soon" })),
        notificationFromDto(
          notificationDto({
            id: "00000000-0000-4000-8000-0000000000f2",
            channel: "email",
            address: "owner@example.com",
            state: "delivered",
            occasion: "reminder",
            updated_at: "2000-01-02T05:00:00Z",
          }),
        ),
      ],
      (id) => `/n/${id}`,
    );
    const { container } = render(<NotificationsTable rows={rows} />);
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(screen.getByText("2 notifications on this page, newest first")).toBeDefined();
    const failed = container.querySelector(
      `[data-notification='${NOTIFICATION_ID}']`,
    ) as HTMLElement;
    expect(
      within(failed).getByRole("link", { name: "Example due soon" }).getAttribute("href"),
    ).toBe(`/n/${NOTIFICATION_ID}`);
    expect(failed.textContent).toContain("example_due_soon");
    expect(failed.textContent).toContain("Sent directly");
    expect(failed.textContent).toContain("*********0000");
    expect(failed.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "danger",
    );
    expect(failed.textContent).toContain(formatDateTime("2000-01-01T05:00:00Z"));
    const delivered = container.querySelector("[data-state='delivered']") as HTMLElement;
    expect(delivered.textContent).toContain("o****@example.com");
    expect(delivered.textContent).toContain("Reminder");
    expect(delivered.textContent).toContain(formatDateTime("2000-01-02T05:00:00Z"));
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
