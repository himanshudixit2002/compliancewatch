import { render, screen, within } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { recipientFromDto, templateFromDto } from "@/entities/notification/mappers";
import type { ActionState } from "@/shared/lib/action-state";
import {
  BUSINESS_ID,
  RECIPIENT_ID,
  TEMPLATE_DTOS,
  recipientDto,
} from "@/test/notification-fixture";
import { recipientsPageView, type RecipientsPageInput } from "../model/page";
import { RecipientsView, type RecipientsViewProps } from "./recipients-view";

const PAGE = "/settings/notifications/recipients";
const OTHER_ID = "00000000-0000-4000-8000-0000000000b2";
const NEW_ID = "00000000-0000-4000-8000-0000000000e9";
const CRUMBS = [
  { id: "owner.settings", href: "/settings", label: "Settings" },
  { id: "owner.settings.notification-recipients", href: PAGE, label: "Notification recipients" },
];
const TABS = [
  { id: "owner.settings.notifications", href: "/settings/notifications", label: "Notifications" },
  { id: "owner.settings.notification-recipients", href: PAGE, label: "Notification recipients" },
];

type Action = (state: ActionState, formData: FormData) => Promise<ActionState>;

function input(overrides: Partial<RecipientsPageInput> = {}): RecipientsPageInput {
  return {
    tenantKind: "business",
    businesses: [
      {
        id: BUSINESS_ID,
        name: "Example business",
        pan: "AAAPE0001Z",
        gstins: [],
        updatedAt: "2000-01-01T00:00:00Z",
      },
      {
        id: OTHER_ID,
        name: "Example second business",
        pan: "AAAPE0002Z",
        gstins: [],
        updatedAt: "2000-01-01T00:00:00Z",
      },
    ],
    moreBusinesses: false,
    selected: { id: BUSINESS_ID, name: "Example business" },
    recipients: [
      recipientFromDto(recipientDto()),
      recipientFromDto(
        recipientDto({
          id: "00000000-0000-4000-8000-0000000000e2",
          org_label: "Example firm",
          role: "staff",
          language: "hi",
          digest_mode: "daily",
          by_digest: true,
          addresses: [],
        }),
      ),
    ],
    moreRecipients: false,
    templates: TEMPLATE_DTOS.map(templateFromDto),
    editing: null,
    editMissing: false,
    newRecipientId: NEW_ID,
    pageHref: PAGE,
    ...overrides,
  };
}

function renderView(overrides: Partial<RecipientsViewProps> = {}, page = input()) {
  return render(
    <RecipientsView
      title="Notification recipients"
      crumbs={CRUMBS}
      tabs={TABS}
      view={recipientsPageView(page)}
      pageHref={PAGE}
      status={{}}
      saveAction={vi.fn<Action>(async () => ({ status: "idle" }))}
      removeAction={vi.fn<Action>(async () => ({ status: "idle" }))}
      addBusinessHref="/onboarding/business"
      {...overrides}
    />,
  );
}

describe("RecipientsView", () => {
  beforeEach(() => {
    vi.mocked(usePathname).mockReturnValue(PAGE);
  });

  it("lists the business's recipients with their addresses, delivery and actions", async () => {
    const { container } = renderView();
    expect(
      screen.getByRole("heading", { level: 1, name: "Notification recipients" }),
    ).toBeDefined();
    expect(
      screen.getByRole("heading", { level: 2, name: "Recipients of Example business" }),
    ).toBeDefined();
    const picker = screen.getByRole("form", { name: "Choose a business" });
    expect(picker.getAttribute("action")).toBe(PAGE);
    expect((within(picker).getByLabelText("Business") as HTMLSelectElement).value).toBe(
      BUSINESS_ID,
    );

    const stats = [...container.querySelectorAll("[data-slot='stat-card'] dd")].map(
      (node) => node.textContent,
    );
    expect(stats).toEqual(["2", "1", "1", "1"]);
    const owner = container.querySelector(`[data-recipient='${RECIPIENT_ID}']`) as HTMLElement;
    expect(owner.textContent).toContain("No organisation named");
    expect([...owner.querySelectorAll("ol li")].map((li) => li.textContent)).toEqual([
      "WhatsApp+910000000000",
      "Emailowner@example.com",
    ]);
    expect(owner.textContent).toContain("Example business");
    expect(owner.textContent).toContain("As they happen");
    expect(owner.textContent).toContain("2 Jan 2000");
    expect(within(owner).getByRole("link", { name: "Change Owner" }).getAttribute("href")).toBe(
      `${PAGE}?business=${BUSINESS_ID}&edit=${RECIPIENT_ID}`,
    );
    expect(within(owner).getByRole("button", { name: "Remove Owner" })).toBeDefined();
    const firm = container.querySelector(
      "[data-recipient='00000000-0000-4000-8000-0000000000e2']",
    ) as HTMLElement;
    expect(firm.textContent).toContain("Example firm");
    expect(firm.textContent).toContain("Hindi");
    expect(firm.textContent).toContain("Daily digest");
    expect(firm.textContent).toContain("None");

    expect(screen.getByRole("heading", { level: 2, name: "Add a recipient" })).toBeDefined();
    expect(screen.getByRole("form", { name: "Add a recipient" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says what the last action did", () => {
    const { rerender } = renderView({ status: { saved: RECIPIENT_ID } });
    expect(screen.getByText("Saved: Owner.")).toBeDefined();
    const props = {
      title: "Notification recipients",
      crumbs: CRUMBS,
      tabs: TABS,
      view: recipientsPageView(input()),
      pageHref: PAGE,
      saveAction: vi.fn<Action>(),
      removeAction: vi.fn<Action>(),
      addBusinessHref: "/onboarding/business",
    };
    rerender(
      <RecipientsView {...props} status={{ saved: "00000000-0000-4000-8000-0000000000ff" }} />,
    );
    expect(screen.getByText("The recipient was saved.")).toBeDefined();
    rerender(<RecipientsView {...props} status={{ removed: true }} />);
    expect(screen.getByText("The recipient was removed.")).toBeDefined();
  });

  it("asks a tenant without a business to add one first", async () => {
    const { container } = renderView({}, input({ businesses: [], selected: null, recipients: [] }));
    expect(screen.getByRole("heading", { level: 2, name: "No business yet" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Add a business" }).getAttribute("href")).toBe(
      "/onboarding/business",
    );
    expect(screen.queryByRole("form")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("explains an empty list, offers the form, and says when the recipient to change is gone", async () => {
    const { container } = renderView(
      {},
      input({
        businesses: [input().businesses[0]!],
        recipients: [],
        editMissing: true,
        moreBusinesses: true,
        moreRecipients: true,
      }),
    );
    expect(screen.queryByRole("form", { name: "Choose a business" })).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "No recipients yet" })).toBeDefined();
    expect(
      screen.getByText("That recipient is not on file any more. Add a new one below."),
    ).toBeDefined();
    expect(screen.getByText("Only the first 200 businesses by name are listed.")).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("changes the recipient chosen, with a way back", () => {
    const editing = recipientFromDto(recipientDto({ org_label: "Example desk" }));
    renderView({}, input({ editing, recipients: [editing], moreRecipients: true }));
    expect(screen.getByRole("heading", { level: 2, name: "Change Example desk" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Cancel" }).getAttribute("href")).toBe(
      `${PAGE}?business=${BUSINESS_ID}`,
    );
    expect(screen.getByText("Only the first 200 recipients are shown.")).toBeDefined();
    expect(screen.getByRole("button", { name: "Save the recipient" })).toBeDefined();
  });
});
