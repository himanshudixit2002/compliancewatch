import type { Route } from "next";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import type { AdminNotificationsData } from "../model/admin-notifications";
import { AdminNotificationsView } from "./admin-notifications-view";

const DATA: AdminNotificationsData = {
  channels: [
    {
      channel: "whatsapp",
      connected: true,
      sentToday: 120,
      dailyQuota: 1000,
      lastSentAt: "2026-10-02T04:00:00Z",
    },
    { channel: "email", connected: false, sentToday: 4, dailyQuota: null, lastSentAt: null },
  ],
  digests: [
    {
      id: "dg-1",
      label: "Owners' morning digest",
      mode: "daily",
      recipientCount: 42,
      lastSentAt: "2026-10-02T02:30:00Z",
    },
    { id: "dg-2", label: "CA firm digest", mode: "off", recipientCount: 3, lastSentAt: null },
  ],
  dispatchLog: [
    {
      id: "ds-1",
      occasion: "reminder",
      channel: "whatsapp",
      recipient: "+919876543210",
      state: "delivered",
      createdAt: "2026-10-02T04:00:00Z",
    },
    {
      id: "ds-2",
      occasion: "change_card",
      channel: "email",
      recipient: "owner@example.com",
      state: "failed",
      createdAt: "2026-10-02T03:00:00Z",
    },
  ],
};

const EMPTY: AdminNotificationsData = { channels: [], digests: [], dispatchLog: [] };

const configureHref = (channel: string) => `/admin/notifications/${channel}` as Route;

function figures(container: HTMLElement): Record<string, { value: string; tone: string }> {
  const cards = [...container.querySelectorAll<HTMLElement>("[data-slot='stat-card']")];
  return Object.fromEntries(
    cards.map((card) => [
      card.querySelector("dt")?.textContent ?? "",
      {
        value: card.querySelector("dd")?.textContent ?? "",
        tone: card.getAttribute("data-tone") ?? "",
      },
    ]),
  );
}

describe("AdminNotificationsView", () => {
  it("summarises the console and opens on the channel cards", async () => {
    const { container } = render(
      <AdminNotificationsView data={DATA} configureHref={configureHref} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Notifications" })).toBeDefined();
    expect(figures(container)).toEqual({
      Dispatches: { value: "2", tone: "neutral" },
      "Delivery rate": { value: "50%", tone: "warning" },
      "Channels connected": { value: "1 of 2", tone: "info" },
      "Digests on": { value: "1", tone: "neutral" },
    });
    expect(screen.getByText("1 delivered, 1 not delivered")).toBeDefined();

    const whatsapp = container.querySelector("[data-channel='whatsapp']") as HTMLElement;
    expect(whatsapp.textContent).toContain("Connected");
    const bar = screen.getByRole("progressbar");
    expect(bar.getAttribute("aria-valuetext")).toBe("120 of 1000");
    expect(whatsapp.textContent).toContain(`Last sent: ${formatDateTime("2026-10-02T04:00:00Z")}`);
    const email = container.querySelector("[data-channel='email']") as HTMLElement;
    expect(email.textContent).toContain("Not connected");
    expect(email.textContent).toContain("Sent today: 4. The provider sets no daily limit.");
    expect(email.textContent).toContain("Last sent: Never");
    expect(screen.getByRole("link", { name: "Configure Email" }).getAttribute("href")).toBe(
      "/admin/notifications/email",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the digest schedules and the dispatch log in their tabs", async () => {
    const user = userEvent.setup();
    const { container } = render(<AdminNotificationsView data={DATA} />);
    expect(screen.queryByRole("link", { name: /Configure/ })).toBeNull();

    await user.click(screen.getByRole("tab", { name: "Digests" }));
    const morning = container.querySelector("[data-digest='dg-1']") as HTMLElement;
    expect(morning.textContent).toContain("Daily");
    expect(morning.textContent).toContain("42");
    expect(morning.textContent).toContain(formatDateTime("2026-10-02T02:30:00Z"));
    const off = container.querySelector("[data-digest='dg-2']") as HTMLElement;
    expect(off.textContent).toContain("Off");
    expect(off.textContent).toContain("Never");
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(screen.getByRole("tab", { name: "Dispatch log" }));
    const failed = container.querySelector("[data-dispatch='ds-2']") as HTMLElement;
    expect(failed.textContent).toContain("Change card");
    expect(failed.textContent).toContain("Email");
    expect(failed.textContent).toContain("Failed");
    expect(failed.textContent).toContain(formatDateTime("2026-10-02T03:00:00Z"));
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says what is missing in every tab when the service reports nothing", async () => {
    const user = userEvent.setup();
    const { container } = render(<AdminNotificationsView data={EMPTY} />);
    expect(figures(container)["Delivery rate"]).toEqual({ value: "None settled", tone: "success" });
    expect(figures(container)["Channels connected"]?.value).toBe("0 of 0");
    expect(screen.getByRole("heading", { level: 2, name: "No channels" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(screen.getByRole("tab", { name: "Digests" }));
    expect(screen.getByRole("heading", { level: 2, name: "No digest schedules" })).toBeDefined();

    await user.click(screen.getByRole("tab", { name: "Dispatch log" }));
    expect(screen.getByRole("heading", { level: 2, name: "No dispatches yet" })).toBeDefined();
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});
