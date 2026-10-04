import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { notificationFromDto } from "@/entities/notification/mappers";
import { formatDateTime } from "@/shared/lib/dates";
import {
  BUSINESS_ID,
  NOTIFICATION_ID,
  OBLIGATION_ID,
  RECIPIENT_ID,
  notificationDto,
} from "@/test/notification-fixture";
import { notificationDetail } from "../model/notifications";
import { NotificationDetail } from "./notification-detail";

function valueOf(container: HTMLElement, label: string): string | null | undefined {
  const term = [...container.querySelectorAll("dt")].find((dt) => dt.textContent === label);
  return term?.nextElementSibling?.textContent;
}

describe("NotificationDetail", () => {
  it("shows the channel's error, the delivery record and the values the message took", async () => {
    const detail = notificationDetail(
      notificationFromDto(
        notificationDto({
          params: { title: "Example title" },
          fallback_of: "00000000-0000-4000-8000-0000000000f0",
        }),
      ),
    );
    const { container } = render(
      <NotificationDetail detail={detail} fallbackHref="/n/00000000-0000-4000-8000-0000000000f0">
        <p>Example note from the page</p>
      </NotificationDetail>,
    );
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("The last attempt failed");
    expect(alert.textContent).toContain("Example channel error");
    expect(valueOf(container, "Delivery")).toBe("Failed");
    expect(valueOf(container, "Channel")).toBe("WhatsApp");
    expect(valueOf(container, "Sent to")).toBe("*********0000");
    expect(valueOf(container, "Occasion")).toBe("Sent directly");
    expect(valueOf(container, "Template")).toBe("example_template");
    expect(valueOf(container, "Language")).toBe("English");
    expect(valueOf(container, "Attempts")).toBe("1");
    expect(valueOf(container, "Queued")).toBe(formatDateTime("2000-01-01T05:00:00Z"));
    expect(valueOf(container, "Sent")).toBe("Not yet");
    expect(
      screen
        .getByRole("link", { name: "00000000-0000-4000-8000-0000000000f0" })
        .getAttribute("href"),
    ).toBe("/n/00000000-0000-4000-8000-0000000000f0");
    expect(valueOf(container, "Obligation id")).toBeUndefined();
    expect(screen.getByRole("button", { name: "Copy Notification id" })).toBeDefined();
    expect(valueOf(container, "title")).toBe("Example title");
    expect(screen.getByText("Example note from the page")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the operator's ids, and says when nothing went wrong and no values were kept", async () => {
    const detail = notificationDetail(
      notificationFromDto(
        notificationDto({
          state: "sent",
          error: "",
          recipient_id: RECIPIENT_ID,
          dispatch_id: "00000000-0000-4000-8000-0000000000d1",
          provider_message_id: "example-provider-id",
        }),
      ),
    );
    const { container } = render(
      <NotificationDetail detail={detail} fallbackHref={null} showIds />,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(valueOf(container, "Business id")).toBe(BUSINESS_ID);
    expect(valueOf(container, "Obligation id")).toBe(OBLIGATION_ID);
    expect(valueOf(container, "Recipient id")).toBe(RECIPIENT_ID);
    expect(valueOf(container, "Dispatch id")).toBe("00000000-0000-4000-8000-0000000000d1");
    expect(valueOf(container, "Provider message id")).toBe("example-provider-id");
    expect(valueOf(container, "Notification id")).toContain(NOTIFICATION_ID);
    expect(screen.getByText(/None recorded/)).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();

    const bare = notificationDetail(
      notificationFromDto(notificationDto({ state: "queued", error: "Example retry error" })),
    );
    const { container: second } = render(
      <NotificationDetail detail={bare} fallbackHref={null} showIds />,
    );
    expect(valueOf(second, "Recipient id")).toBe("None: sent straight to the address");
    expect(valueOf(second, "Dispatch id")).toBe("None");
    expect(valueOf(second, "Provider message id")).toBe("None");
    expect(second.querySelector("[data-slot='banner']")?.getAttribute("data-tone")).toBe("warning");
  });
});
