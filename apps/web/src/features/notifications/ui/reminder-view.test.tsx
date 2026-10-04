import { render, screen } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { notificationFromDto } from "@/entities/notification/mappers";
import { BUSINESS_ID, NOTIFICATION_ID, notificationDto } from "@/test/notification-fixture";
import { notificationDetail } from "../model/notifications";
import { ReminderView } from "./reminder-view";

const LIST = `/b/${BUSINESS_ID}/reminders`;

describe("ReminderView", () => {
  beforeEach(() => {
    vi.mocked(usePathname).mockReturnValue(`${LIST}/${NOTIFICATION_ID}`);
  });

  it("names the notification by its template and shows its record with the way back", async () => {
    const { container } = render(
      <ReminderView
        view={{
          business: { id: BUSINESS_ID, name: "Example business", pan: "AAAPE0001Z" },
          detail: notificationDetail(
            notificationFromDto(
              notificationDto({ template_key: "example_due_soon", language: "hi" }),
            ),
          ),
          listHref: LIST,
          fallbackHref: null,
        }}
        header={{
          crumbs: [
            { id: "owner.reminders", href: LIST, label: "Reminders" },
            { id: "owner.reminder", href: `${LIST}/${NOTIFICATION_ID}`, label: "Example due soon" },
          ],
          tabs: [
            { id: "owner.business", href: `/b/${BUSINESS_ID}`, label: "Business" },
            { id: "owner.reminders", href: LIST, label: "Reminders" },
          ],
        }}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Example due soon" })).toBeDefined();
    expect(
      screen.getByText(
        "Template example_due_soon, Sent directly, in Hindi. The service keeps the delivery record, not the text of the message.",
      ),
    ).toBeDefined();
    expect(
      screen.getByRole("link", { name: "All notifications of this business" }).getAttribute("href"),
    ).toBe(LIST);
    expect(screen.getByRole("link", { name: "Reminders", current: "page" })).toBeDefined();
    expect(container.querySelector("[data-slot='notification-detail']")).not.toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
