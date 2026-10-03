import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { formatDate, formatDateTime } from "@/shared/lib/dates";
import type { Webhook } from "../model/webhooks";
import { WebhooksView } from "./webhooks-view";

type Action = (formData: FormData) => Promise<void>;

const CRUMBS = [
  { id: "owner.settings", href: "/settings", label: "Settings" },
  { id: "ca.settings.webhooks", href: "/settings/webhooks", label: "Webhooks" },
];
const TABS = [{ id: "owner.settings.consents", href: "/settings/consents", label: "Consents" }];

const WEBHOOKS: Webhook[] = [
  {
    id: "wh_erp",
    url: "https://erp.example.com/hooks/compliance",
    events: ["rule.published", "obligation.created"],
    status: "active",
    createdAt: "2026-06-05T05:00:00Z",
    lastDelivery: { at: "2026-10-02T04:30:00Z", statusCode: 200 },
  },
  {
    id: "wh_crm",
    url: "https://crm.example.com/in",
    events: ["obligation.due_soon"],
    status: "paused",
    createdAt: "2026-07-01T05:00:00Z",
    lastDelivery: { at: "2026-10-01T10:00:00Z", statusCode: 503 },
  },
  {
    id: "wh_new",
    url: "https://new.example.com/hook",
    events: ["obligation.closed"],
    status: "active",
    createdAt: "2026-10-02T05:00:00Z",
    lastDelivery: null,
  },
];

function row(container: HTMLElement, id: string): HTMLElement {
  return container.querySelector(`[data-webhook='${id}']`) as HTMLElement;
}

function chips(element: HTMLElement): { text: string; tone: string | null }[] {
  return [...element.querySelectorAll("[data-slot='status-chip']")].map((chip) => ({
    text: chip.textContent ?? "",
    tone: chip.getAttribute("data-tone"),
  }));
}

describe("WebhooksView", () => {
  it("lists each endpoint's events, status and latest delivery, and warns of pauses", async () => {
    const { container } = render(
      <WebhooksView title="Webhooks" webhooks={WEBHOOKS} crumbs={CRUMBS} tabs={TABS} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Webhooks" })).toBeDefined();
    const banner = screen.getByRole("status");
    expect(banner.textContent).toContain("Paused endpoints: 1 of 3");
    expect(banner.textContent).toContain("failed for 24 hours");
    expect(screen.getByText("Endpoints: 3. Paused: 1.")).toBeDefined();
    expect(screen.getAllByRole("columnheader")).toHaveLength(4);

    const erp = row(container, "wh_erp");
    expect(within(erp).getByText("https://erp.example.com/hooks/compliance")).toBeDefined();
    expect(erp.textContent).toContain(`Added ${formatDate("2026-06-05T05:00:00Z")}`);
    expect(
      within(erp)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["A rule is published", "An obligation is created"]);
    expect(chips(erp)).toEqual([
      { text: "Active", tone: "success" },
      { text: `Delivered ${formatDateTime("2026-10-02T04:30:00Z")}: HTTP 200`, tone: "success" },
    ]);
    expect(chips(row(container, "wh_crm"))).toEqual([
      { text: "Paused", tone: "warning" },
      { text: `Failed ${formatDateTime("2026-10-01T10:00:00Z")}: HTTP 503`, tone: "danger" },
    ]);
    expect(chips(row(container, "wh_new"))[1]).toEqual({
      text: "Nothing sent yet",
      tone: "neutral",
    });

    expect(screen.queryByRole("heading", { name: "Add an endpoint" })).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("adds an endpoint with the events left ticked", async () => {
    const user = userEvent.setup();
    let sent: FormData | undefined;
    const createAction = vi.fn<Action>(async (formData) => {
      sent = formData;
    });
    const { container } = render(
      <WebhooksView
        title="Webhooks"
        webhooks={WEBHOOKS}
        crumbs={CRUMBS}
        tabs={TABS}
        createAction={createAction}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Add an endpoint" })).toBeDefined();
    const url = screen.getByRole("textbox", { name: "Endpoint address" });
    expect(url.getAttribute("type")).toBe("url");
    expect(url.getAttribute("pattern")).toBe("https://.+");
    expect(url.hasAttribute("required")).toBe(true);
    const events = within(screen.getByRole("group", { name: "Events to send" })).getAllByRole(
      "checkbox",
    );
    expect(events.map((box) => box.getAttribute("aria-checked"))).toEqual([
      "true",
      "true",
      "true",
      "true",
      "true",
    ]);
    expect(await runAxe(container)).toHaveNoViolations();

    await user.type(url, "https://books.example.com/cw");
    await user.click(
      screen.getByRole("checkbox", { name: "A rule is replaced by a newer version" }),
    );
    await user.click(screen.getByRole("button", { name: "Add endpoint" }));
    await waitFor(() => expect(createAction).toHaveBeenCalledTimes(1));
    expect(sent?.get("url")).toBe("https://books.example.com/cw");
    expect(sent?.getAll("events")).toEqual([
      "rule.published",
      "obligation.created",
      "obligation.due_soon",
      "obligation.closed",
    ]);
  });

  it("sends a test event, and removes an endpoint only once confirmed", async () => {
    const user = userEvent.setup();
    let tested: FormData | undefined;
    let removed: FormData | undefined;
    const testAction = vi.fn<Action>(async (formData) => {
      tested = formData;
    });
    const removeAction = vi.fn<Action>(async (formData) => {
      removed = formData;
    });
    const { container } = render(
      <WebhooksView
        title="Webhooks"
        webhooks={WEBHOOKS}
        crumbs={CRUMBS}
        tabs={TABS}
        testAction={testAction}
        removeAction={removeAction}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Actions" })).toBeDefined();
    expect(screen.getAllByRole("button", { name: /^Send test event/ })).toHaveLength(3);
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(
      screen.getByRole("button", {
        name: "Send test event https://erp.example.com/hooks/compliance",
      }),
    );
    await waitFor(() => expect(testAction).toHaveBeenCalledTimes(1));
    expect(tested?.get("webhook_id")).toBe("wh_erp");

    await user.click(screen.getByRole("button", { name: "Remove https://crm.example.com/in" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove this endpoint?" });
    expect(dialog.textContent).toContain("No more events are sent to https://crm.example.com/in.");
    expect(removeAction).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Remove endpoint" }));
    await waitFor(() => expect(removeAction).toHaveBeenCalledTimes(1));
    expect(removed?.get("webhook_id")).toBe("wh_crm");
  });

  it("offers only the row actions it was given", () => {
    const only = (props: { testAction?: Action; removeAction?: Action }) =>
      render(
        <WebhooksView
          title="Webhooks"
          webhooks={WEBHOOKS.slice(0, 1)}
          crumbs={CRUMBS}
          tabs={TABS}
          {...props}
        />,
      );
    const tests = only({ testAction: vi.fn<Action>(async () => undefined) });
    expect(screen.getByRole("button", { name: /^Send test event/ })).toBeDefined();
    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
    tests.unmount();

    only({ removeAction: vi.fn<Action>(async () => undefined) });
    expect(screen.getByRole("button", { name: /^Remove/ })).toBeDefined();
    expect(screen.queryByRole("button", { name: /^Send test event/ })).toBeNull();
  });

  it("explains an empty list without a warning", async () => {
    const { container } = render(
      <WebhooksView title="Webhooks" webhooks={[]} crumbs={CRUMBS} tabs={TABS} />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No endpoints" })).toBeDefined();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
