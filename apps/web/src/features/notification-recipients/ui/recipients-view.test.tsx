import { render, screen } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Recipient } from "../model/recipients";
import { RecipientsView } from "./recipients-view";

const CRUMBS = [
  { id: "owner.settings", href: "/settings", label: "Settings" },
  {
    id: "owner.settings.notification-recipients",
    href: "/settings/notifications/recipients",
    label: "Notification recipients",
  },
];
const TABS = [
  { id: "owner.settings.notifications", href: "/settings/notifications", label: "Notifications" },
];

const RECIPIENTS: Recipient[] = [
  {
    id: "r2",
    orgLabel: "",
    role: "staff",
    language: "en",
    addresses: [],
    businesses: [],
    byDigest: false,
    updatedAt: "2000-05-02T05:00:00Z",
  },
  {
    id: "r1",
    orgLabel: "Example & Co",
    role: "ca_admin",
    language: "hi",
    addresses: [
      { channel: "whatsapp", address: "+910000000001" },
      { channel: "email", address: "desk@firm.example" },
    ],
    businesses: ["Example business 1", "Example business 2"],
    byDigest: true,
    updatedAt: "2000-04-10T05:00:00Z",
  },
];

describe("RecipientsView", () => {
  beforeEach(() => {
    vi.mocked(usePathname).mockReturnValue("/settings/notifications/recipients");
  });

  it("shows the summary and each recipient with addresses, businesses and delivery", async () => {
    const { container } = render(
      <RecipientsView
        title="Notification recipients"
        recipients={RECIPIENTS}
        crumbs={CRUMBS}
        tabs={TABS}
      />,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Notification recipients" }),
    ).toBeDefined();
    expect(screen.getByText("2 recipients")).toBeDefined();
    const stats = container.querySelectorAll("[data-slot='stat-card']");
    expect([...stats].map((card) => card.textContent)).toEqual([
      "Recipients2",
      "Reachable on WhatsApp1",
      "Reachable by email1",
      "On the daily digest1",
    ]);

    const rows = container.querySelectorAll("tbody tr");
    expect([...rows].map((row) => row.getAttribute("data-recipient"))).toEqual(["r1", "r2"]);
    const firm = rows[0] as HTMLElement;
    expect(firm.textContent).toContain("Example & Co");
    expect(firm.textContent).toContain("CA admin");
    expect([...firm.querySelectorAll("ol li")].map((li) => li.textContent)).toEqual([
      "WhatsApp+910000000001",
      "Emaildesk@firm.example",
    ]);
    expect(firm.textContent).toContain("Example business 1, Example business 2");
    expect(firm.textContent).toContain("Hindi");
    expect(firm.textContent).toContain("Daily digest");
    expect(firm.textContent).toContain("10 Apr 2000");

    const unnamed = rows[1] as HTMLElement;
    expect(unnamed.textContent).toContain("No organisation named");
    expect(unnamed.textContent).toContain("Staff");
    expect(unnamed.querySelector("ol")).toBeNull();
    expect(unnamed.textContent).toContain("None");
    expect(unnamed.textContent).toContain("English");
    expect(unnamed.textContent).toContain("As they happen");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("explains an empty list instead of an empty table", async () => {
    const { container } = render(
      <RecipientsView
        title="Notification recipients"
        recipients={[]}
        crumbs={CRUMBS}
        tabs={TABS}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No recipients yet" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
