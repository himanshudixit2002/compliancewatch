import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { NotificationDetail } from "./notification-detail";

const VIEW = {
  id: "ntf-1",
  subject: "GST return filed successfully",
  channel: "email" as const,
  status: "delivered" as const,
  recipient: "owner@example.com",
  sentAt: "2024-01-15 10:30",
  readAt: "2024-01-15 11:00",
  templateKey: "gst_filed",
  body: "Your GST return has been filed successfully for the period.",
  tenantName: "Acme Pvt Ltd",
  deliveryAttempts: 1,
  errorMessage: null,
};

describe("NotificationDetail", () => {
  it("renders the subject heading and key-value fields", async () => {
    const { container } = render(
      <NotificationDetail view={VIEW} backHref="/account/notifications" />,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "GST return filed successfully" }),
    ).toBeDefined();
    expect(screen.getByText("owner@example.com")).toBeDefined();
    expect(screen.getByText("Acme Pvt Ltd")).toBeDefined();
    expect(screen.getByText("gst_filed")).toBeDefined();
    expect(
      screen.getByText("Your GST return has been filed successfully for the period."),
    ).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows a delivery error card when present", async () => {
    const withError = { ...VIEW, errorMessage: "SMTP connection timeout" };
    const { container } = render(
      <NotificationDetail view={withError} backHref="/account/notifications" />,
    );
    expect(screen.getByText("SMTP connection timeout")).toBeDefined();
    expect(screen.getByText("Delivery error")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
