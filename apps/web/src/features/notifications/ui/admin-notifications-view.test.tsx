import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { notificationFromDto } from "@/entities/notification/mappers";
import { BUSINESS_ID, notificationDto } from "@/test/notification-fixture";
import type { AdminNotificationsView as AdminNotificationsViewModel } from "../model/history";
import { readLookup } from "../model/lookup";
import { notificationRows } from "../model/notifications";
import {
  AdminNotificationsView,
  type AdminNotificationsViewProps,
} from "./admin-notifications-view";

const TENANT = "00000000-0000-4000-8000-0000000000a9";
const PAGE = "/admin/notifications";
const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.notifications", href: PAGE, label: "Notifications" },
];

function viewModel(
  overrides: Partial<AdminNotificationsViewModel> = {},
): AdminNotificationsViewModel {
  return {
    lookup: { tenantId: TENANT, businessId: BUSINESS_ID },
    rows: notificationRows([notificationFromDto(notificationDto())], (id) => `${PAGE}/${id}`),
    filter: {},
    nextHref: null,
    firstHref: null,
    ...overrides,
  };
}

function renderView(props: Partial<AdminNotificationsViewProps>) {
  return render(
    <AdminNotificationsView
      title="Notifications"
      crumbs={CRUMBS}
      pageHref={PAGE}
      templatesHref={`${PAGE}/templates`}
      lookup={{ kind: "empty" }}
      view={null}
      {...props}
    />,
  );
}

describe("AdminNotificationsView", () => {
  it("asks for a tenant and a business before reading anything", async () => {
    const { container } = renderView({});
    expect(screen.getByRole("heading", { level: 1, name: "Notifications" })).toBeDefined();
    const form = screen.getByRole("form", { name: "Look up a business's notifications" });
    expect(form.getAttribute("method")).toBe("get");
    expect(form.getAttribute("action")).toBe(PAGE);
    expect(screen.getByRole("link", { name: "Message templates" }).getAttribute("href")).toBe(
      `${PAGE}/templates`,
    );
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText(/Give a tenant id and the id of one of its businesses/)).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("marks an id that is not one and keeps what was typed", async () => {
    const { container } = renderView({
      lookup: readLookup({ tenant: "nope", business: BUSINESS_ID }),
    });
    const tenant = screen.getByLabelText(/^Tenant id/) as HTMLInputElement;
    expect(tenant.value).toBe("nope");
    expect(tenant.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Enter the tenant's id, a UUID.")).toBeDefined();
    expect((screen.getByLabelText(/^Business id/) as HTMLInputElement).value).toBe(BUSINESS_ID);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the business's history with the filter keeping the lookup", async () => {
    const { container } = renderView({
      lookup: readLookup({ tenant: TENANT, business: BUSINESS_ID }),
      view: viewModel({ nextHref: `${PAGE}?cursor=next` }),
    });
    expect(
      screen.getByRole("heading", { level: 2, name: "Notifications of the business" }),
    ).toBeDefined();
    expect(
      screen.getByText(`Business ${BUSINESS_ID} of tenant ${TENANT}, newest first.`),
    ).toBeDefined();
    const filter = screen.getByRole("form", { name: "Filter the notifications" });
    expect((filter.querySelector("input[name='tenant']") as HTMLInputElement).value).toBe(TENANT);
    expect((filter.querySelector("input[name='business']") as HTMLInputElement).value).toBe(
      BUSINESS_ID,
    );
    expect(screen.getByRole("table")).toBeDefined();
    expect(screen.getByRole("link", { name: "Older notifications" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says why a history is empty and shows a failed read under the form", () => {
    const { rerender } = renderView({
      lookup: readLookup({ tenant: TENANT, business: BUSINESS_ID }),
      view: viewModel({ rows: [] }),
    });
    expect(
      screen.getByRole("heading", { level: 2, name: "No notifications for this business" }),
    ).toBeDefined();
    rerender(
      <AdminNotificationsView
        title="Notifications"
        crumbs={CRUMBS}
        pageHref={PAGE}
        templatesHref={`${PAGE}/templates`}
        lookup={readLookup({ tenant: TENANT, business: BUSINESS_ID })}
        view={viewModel({ rows: [], filter: { state: "sent" } })}
      />,
    );
    expect(screen.getByText(/in the state Sent\./)).toBeDefined();
    rerender(
      <AdminNotificationsView
        title="Notifications"
        crumbs={CRUMBS}
        pageHref={PAGE}
        templatesHref={`${PAGE}/templates`}
        lookup={readLookup({ tenant: TENANT, business: BUSINESS_ID })}
        view={null}
        error={{ message: "Example outage", status: 503, requestId: "req-9" }}
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain("Example outage");
    expect(screen.getByText("req-9")).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
