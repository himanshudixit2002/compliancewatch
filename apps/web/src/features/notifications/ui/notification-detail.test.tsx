import type { Route } from "next";
import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import type { NotificationRecord } from "../model/notifications";
import { NotificationDetail } from "./notification-detail";

const RECORD: NotificationRecord = {
  id: "ntf-1",
  subject: "GST return filed successfully",
  channel: "email",
  state: "read",
  recipient: "owner@example.com",
  templateKey: "gst_filed",
  sentAt: "2026-10-01T05:00:00Z",
  body: "Your GST return has been filed\nfor September.",
  businessName: "Acme Pvt Ltd",
  attempts: 1,
  deliveredAt: "2026-10-01T05:01:00Z",
  readAt: "2026-10-01T06:00:00Z",
  error: null,
};

const LIST = "/account/notifications" as Route;

function valueOf(container: HTMLElement, label: string): string | null | undefined {
  const term = [...container.querySelectorAll("dt")].find((dt) => dt.textContent === label);
  return term?.nextElementSibling?.textContent;
}

describe("NotificationDetail", () => {
  it("shows the delivery record, the message and a link back to the list", async () => {
    const { container } = render(<NotificationDetail notification={RECORD} listHref={LIST} />);
    expect(
      screen.getByRole("heading", { level: 1, name: "GST return filed successfully" }),
    ).toBeDefined();
    expect(screen.getByRole("link", { name: "All notifications" }).getAttribute("href")).toBe(
      "/account/notifications",
    );
    expect(valueOf(container, "Delivery")).toBe("Read");
    expect(valueOf(container, "Channel")).toBe("Email");
    expect(valueOf(container, "Recipient")).toBe("owner@example.com");
    expect(valueOf(container, "Business")).toBe("Acme Pvt Ltd");
    expect(valueOf(container, "Template")).toBe("gst_filed");
    expect(valueOf(container, "Sent")).toBe(formatDateTime("2026-10-01T05:00:00Z"));
    expect(valueOf(container, "Read")).toBe(formatDateTime("2026-10-01T06:00:00Z"));
    expect(valueOf(container, "Attempts")).toBe("1");
    expect(screen.getByRole("button", { name: "Copy Notification id" })).toBeDefined();
    expect(screen.getByText(/for September\./).textContent).toBe(RECORD.body);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the delivery error and None for what never happened", async () => {
    const failed: NotificationRecord = {
      ...RECORD,
      state: "failed",
      sentAt: null,
      deliveredAt: null,
      readAt: null,
      businessName: null,
      attempts: 3,
      error: "SMTP connection timeout",
    };
    const { container } = render(<NotificationDetail notification={failed} listHref={LIST} />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Delivery failed");
    expect(alert.textContent).toContain("SMTP connection timeout");
    expect(valueOf(container, "Business")).toBe("None");
    expect(valueOf(container, "Sent")).toBe("None");
    expect(valueOf(container, "Delivered")).toBe("None");
    expect(valueOf(container, "Read")).toBe("None");
    expect(container.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "danger",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
