import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import type { DigestRecipient } from "../model/digests";
import { DigestsView } from "./digests-view";

type Action = (formData: FormData) => Promise<void>;

const CRUMBS = [
  { id: "owner.settings", href: "/settings", label: "Settings" },
  { id: "ca.settings.digests", href: "/settings/digests", label: "Digests" },
];
const TABS = [{ id: "owner.settings.consents", href: "/settings/consents", label: "Consents" }];

const RECIPIENTS: DigestRecipient[] = [
  {
    id: "rcp_ravi",
    name: "Ravi Kumar",
    address: "+919800000002",
    mode: "off",
    clientCount: 4,
    lastSentAt: null,
  },
  {
    id: "rcp_asha",
    name: "Asha Rao",
    address: "asha@raoandco.example.com",
    mode: "daily",
    clientCount: 12,
    lastSentAt: "2026-10-02T03:30:00Z",
  },
];

function row(container: HTMLElement, id: string): HTMLElement {
  return container.querySelector(`[data-recipient='${id}']`) as HTMLElement;
}

describe("DigestsView", () => {
  it("lists the firm's people by name: clients, how they hear and their last digest", async () => {
    const { container } = render(
      <DigestsView title="Digests" recipients={RECIPIENTS} crumbs={CRUMBS} tabs={TABS} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Digests" })).toBeDefined();
    expect(screen.getByText("On the daily digest: 1 of 2")).toBeDefined();
    expect(
      [...container.querySelectorAll("tbody tr")].map((tr) => tr.getAttribute("data-recipient")),
    ).toEqual(["rcp_asha", "rcp_ravi"]);

    const asha = row(container, "rcp_asha");
    expect(asha.textContent).toContain("asha@raoandco.example.com");
    expect(within(asha).getAllByRole("cell")[1]?.textContent).toBe("12");
    const daily = asha.querySelector("[data-slot='status-chip']");
    expect(daily?.textContent).toBe("Daily digest");
    expect(daily?.getAttribute("data-tone")).toBe("info");
    expect(asha.textContent).toContain(formatDateTime("2026-10-02T03:30:00Z"));

    const ravi = row(container, "rcp_ravi");
    const off = ravi.querySelector("[data-slot='status-chip']");
    expect(off?.textContent).toBe("Each change on its own");
    expect(off?.getAttribute("data-tone")).toBe("neutral");
    expect(ravi.textContent).toContain("Never");

    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("saves the mode chosen for one person", async () => {
    const user = userEvent.setup();
    let sent: FormData | undefined;
    const saveAction = vi.fn<Action>(async (formData) => {
      sent = formData;
    });
    const { container } = render(
      <DigestsView
        title="Digests"
        recipients={RECIPIENTS}
        crumbs={CRUMBS}
        tabs={TABS}
        saveAction={saveAction}
      />,
    );
    expect(container.querySelector("[data-slot='status-chip']")).toBeNull();
    const ravi = screen.getByRole("combobox", { name: "How Ravi Kumar hears about changes" });
    expect((ravi as HTMLSelectElement).value).toBe("off");
    expect(
      (
        screen.getByRole("combobox", {
          name: "How Asha Rao hears about changes",
        }) as HTMLSelectElement
      ).value,
    ).toBe("daily");
    expect(
      within(ravi)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Daily digest", "Each change on its own"]);
    expect(await runAxe(container)).toHaveNoViolations();

    await user.selectOptions(ravi, "daily");
    await user.click(screen.getByRole("button", { name: "Save Ravi Kumar" }));
    await waitFor(() => expect(saveAction).toHaveBeenCalledTimes(1));
    expect(sent?.get("recipient_id")).toBe("rcp_ravi");
    expect(sent?.get("mode")).toBe("daily");
  });

  it("explains an empty list", async () => {
    const { container } = render(
      <DigestsView title="Digests" recipients={[]} crumbs={CRUMBS} tabs={TABS} />,
    );
    expect(
      screen.getByRole("heading", { level: 2, name: "No one to send digests to" }),
    ).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
