import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { notificationFromDto } from "@/entities/notification/mappers";
import {
  BUSINESS_ID,
  NOTIFICATION_ID,
  OBLIGATION_ID,
  notificationDto,
} from "@/test/notification-fixture";
import { notificationDetail } from "../model/notifications";
import { AdminNotificationView, TenantNeededView } from "./admin-notification-view";

const TENANT = "00000000-0000-4000-8000-0000000000a9";
const LIST = `/admin/notifications?tenant=${TENANT}&business=${BUSINESS_ID}`;
const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.notifications", href: LIST, label: "Notifications" },
  {
    id: "admin.notification",
    href: `/admin/notifications/${NOTIFICATION_ID}`,
    label: "Example template",
  },
];

function valueOf(container: HTMLElement, label: string): string | null | undefined {
  const term = [...container.querySelectorAll("dt")].find((dt) => dt.textContent === label);
  return term?.nextElementSibling?.textContent;
}

describe("AdminNotificationView", () => {
  it("shows the record with the operator's ids, the tenant, and what resending waits for", async () => {
    const { container } = render(
      <AdminNotificationView
        crumbs={CRUMBS}
        view={{
          tenantId: TENANT,
          detail: notificationDetail(notificationFromDto(notificationDto())),
          listHref: LIST,
          fallbackHref: null,
        }}
        resend={{
          title: "Resend a notification",
          waitingFor: [
            {
              method: "POST",
              path: "/v1/notification/notifications/{notification_id}/resend",
              owner: "services track (WP30), requiring Idempotency-Key",
            },
          ],
        }}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Example template" })).toBeDefined();
    expect(screen.getByText(`Tenant ${TENANT}`)).toBeDefined();
    expect(
      screen.getByRole("link", { name: "All notifications of this business" }).getAttribute("href"),
    ).toBe(LIST);
    expect(valueOf(container, "Obligation id")).toBe(OBLIGATION_ID);
    expect(valueOf(container, "Business id")).toBe(BUSINESS_ID);
    expect(screen.getByText("Resend a notification: not offered yet")).toBeDefined();
    expect(container.querySelector("[data-slot='resend-awaits']")?.textContent).toContain(
      "POST /v1/notification/notifications/{notification_id}/resend (services track (WP30), requiring Idempotency-Key)",
    );
    expect(screen.queryByRole("button", { name: /resend/i })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("leaves the resend note out for a role it is not for", () => {
    render(
      <AdminNotificationView
        crumbs={CRUMBS}
        view={{
          tenantId: TENANT,
          detail: notificationDetail(notificationFromDto(notificationDto())),
          listHref: LIST,
          fallbackHref: null,
        }}
        resend={null}
      />,
    );
    expect(screen.queryByText(/not offered yet/)).toBeNull();
  });
});

describe("TenantNeededView", () => {
  it("asks for the tenant a notification belongs to, with the value and its error", async () => {
    const { container } = render(
      <TenantNeededView
        title="Notification"
        crumbs={CRUMBS.slice(0, 2)}
        action={`/admin/notifications/${NOTIFICATION_ID}`}
        value="nope"
        error="Enter the tenant's id, a UUID."
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Notification" })).toBeDefined();
    const form = screen.getByRole("form", { name: "The notification's tenant" });
    expect(form.getAttribute("action")).toBe(`/admin/notifications/${NOTIFICATION_ID}`);
    const input = screen.getByLabelText(/^Tenant id/) as HTMLInputElement;
    expect(input.value).toBe("nope");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByRole("button", { name: "Open the notification" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
