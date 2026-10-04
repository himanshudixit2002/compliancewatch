import { render, screen } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { notificationFromDto } from "@/entities/notification/mappers";
import { BUSINESS_ID, notificationDto } from "@/test/notification-fixture";
import type { RemindersView as RemindersViewModel } from "../model/history";
import { notificationRows } from "../model/notifications";
import { RemindersView } from "./reminders-view";

const LIST = `/b/${BUSINESS_ID}/reminders`;
const HEADER = {
  crumbs: [
    { id: "owner.businesses", href: "/businesses", label: "Businesses" },
    { id: "owner.business", href: `/b/${BUSINESS_ID}`, label: "Example business" },
    { id: "owner.reminders", href: LIST, label: "Reminders" },
  ],
  tabs: [
    { id: "owner.business", href: `/b/${BUSINESS_ID}`, label: "Business" },
    { id: "owner.reminders", href: LIST, label: "Reminders" },
  ],
};
const BUSINESS = { id: BUSINESS_ID, name: "Example business", pan: "AAAPE0001Z" };

function view(overrides: Partial<RemindersViewModel> = {}): RemindersViewModel {
  return {
    business: BUSINESS,
    rows: notificationRows([notificationFromDto(notificationDto())], (id) => `${LIST}/${id}`),
    filter: {},
    nextHref: `${LIST}?cursor=next`,
    firstHref: null,
    ...overrides,
  };
}

describe("RemindersView", () => {
  beforeEach(() => {
    vi.mocked(usePathname).mockReturnValue(LIST);
  });

  it("shows the business's notifications with the filter and the way to older ones", async () => {
    const { container } = render(
      <RemindersView title="Reminders" view={view()} header={HEADER} pageHref={LIST} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Reminders" })).toBeDefined();
    expect(screen.getByText("Example business, PAN AAAPE0001Z.")).toBeDefined();
    const filter = screen.getByRole("form", { name: "Filter the notifications" });
    expect(filter.getAttribute("action")).toBe(LIST);
    expect((screen.getByLabelText("Delivery state") as HTMLSelectElement).value).toBe("");
    expect(screen.getByRole("table")).toBeDefined();
    expect(screen.getByRole("link", { name: "Older notifications" }).getAttribute("href")).toBe(
      `${LIST}?cursor=next`,
    );
    expect(screen.queryByRole("link", { name: "Back to the newest" })).toBeNull();
    expect(screen.getByRole("navigation", { name: "Pages of this business" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says why the history is empty, with and without a state chosen", async () => {
    const { rerender, container } = render(
      <RemindersView
        title="Reminders"
        view={view({ rows: [], nextHref: null })}
        header={HEADER}
        pageHref={LIST}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No notifications yet" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("navigation", { name: "More notifications" })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
    rerender(
      <RemindersView
        title="Reminders"
        view={view({
          rows: [],
          nextHref: null,
          filter: { state: "read", cursor: "now" },
          firstHref: `${LIST}?state=read`,
        })}
        header={HEADER}
        pageHref={LIST}
      />,
    );
    expect(
      screen.getByRole("heading", { level: 2, name: "No notification in this state" }),
    ).toBeDefined();
    expect(screen.getByText(/in the state Read\./)).toBeDefined();
    expect((screen.getByLabelText("Delivery state") as HTMLSelectElement).value).toBe("read");
    expect(screen.getByRole("link", { name: "Back to the newest" }).getAttribute("href")).toBe(
      `${LIST}?state=read`,
    );
  });
});
