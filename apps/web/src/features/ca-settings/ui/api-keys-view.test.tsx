import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { formatDate, formatDateTime } from "@/shared/lib/dates";
import type { ApiKey } from "../model/api-keys";
import { ApiKeysView } from "./api-keys-view";

type Action = (formData: FormData) => Promise<void>;

const CRUMBS = [
  { id: "owner.settings", href: "/settings", label: "Settings" },
  { id: "ca.settings.api-keys", href: "/settings/api-keys", label: "API keys" },
];
const TABS = [{ id: "owner.settings.consents", href: "/settings/consents", label: "Consents" }];

const KEYS: ApiKey[] = [
  {
    id: "key_old",
    name: "Old export",
    prefix: "cw_live_",
    lastFour: "77c0",
    createdAt: "2026-01-15T05:00:00Z",
    lastUsedAt: "2026-03-01T05:00:00Z",
    revokedAt: "2026-04-10T05:00:00Z",
  },
  {
    id: "key_tally",
    name: "Tally sync",
    prefix: "cw_live_",
    lastFour: "3f9a",
    createdAt: "2026-04-02T05:00:00Z",
    lastUsedAt: null,
    revokedAt: null,
  },
  {
    id: "key_ci",
    name: "CI deploy",
    prefix: "cw_test_",
    lastFour: "a1b2",
    createdAt: "2026-08-10T05:00:00Z",
    lastUsedAt: "2026-10-01T06:15:00Z",
    revokedAt: null,
  },
];

function row(container: HTMLElement, id: string): HTMLElement {
  return container.querySelector(`[data-api-key='${id}']`) as HTMLElement;
}

describe("ApiKeysView", () => {
  it("lists every key, working ones first, by name, hint, dates and status", async () => {
    const { container } = render(
      <ApiKeysView title="API keys" keys={KEYS} crumbs={CRUMBS} tabs={TABS} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "API keys" })).toBeDefined();
    expect(screen.getByText("2 active, 1 revoked")).toBeDefined();
    expect(
      [...container.querySelectorAll("tbody tr")].map((tr) => tr.getAttribute("data-api-key")),
    ).toEqual(["key_ci", "key_tally", "key_old"]);
    expect(screen.getAllByRole("columnheader")).toHaveLength(5);

    const ci = row(container, "key_ci");
    expect(ci.textContent).toContain("CI deploy");
    expect(within(ci).getByText("cw_test_…a1b2")).toBeDefined();
    expect(ci.textContent).toContain(formatDate("2026-08-10T05:00:00Z"));
    expect(ci.textContent).toContain(formatDateTime("2026-10-01T06:15:00Z"));
    const chip = ci.querySelector("[data-slot='status-chip']");
    expect(chip?.textContent).toBe("Active");
    expect(chip?.getAttribute("data-tone")).toBe("success");

    expect(row(container, "key_tally").textContent).toContain("Never");

    const old = row(container, "key_old");
    expect(old.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "neutral",
    );
    expect(old.textContent).toContain("Revoked on 10 Apr 2026");

    expect(screen.queryByRole("heading", { name: "Create a key" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Revoke/ })).toBeNull();
    expect(container.querySelector("[data-slot='new-api-key']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("never shows more of a listed key than its hint", () => {
    const secret = "cw_live_9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e";
    const leaky: ApiKey = { ...KEYS[1]!, prefix: secret, lastFour: secret };
    const { container } = render(
      <ApiKeysView title="API keys" keys={[leaky]} crumbs={CRUMBS} tabs={TABS} />,
    );
    expect(container.textContent).not.toContain(secret);
    expect(row(container, "key_tally").querySelector("code")?.textContent).toBe(
      "cw_live_9b8c…5d4e",
    );
  });

  it("creates a key from the name typed in", async () => {
    const user = userEvent.setup();
    let sent: FormData | undefined;
    const createAction = vi.fn<Action>(async (formData) => {
      sent = formData;
    });
    const { container } = render(
      <ApiKeysView
        title="API keys"
        keys={KEYS}
        crumbs={CRUMBS}
        tabs={TABS}
        createAction={createAction}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Create a key" })).toBeDefined();
    const name = screen.getByRole("textbox", { name: "Name" });
    expect(name.getAttribute("maxlength")).toBe("80");
    expect(name.hasAttribute("required")).toBe(true);
    expect(await runAxe(container)).toHaveNoViolations();

    await user.type(name, "ERP connector");
    await user.click(screen.getByRole("button", { name: "Create key" }));
    await waitFor(() => expect(createAction).toHaveBeenCalledTimes(1));
    expect(sent?.get("name")).toBe("ERP connector");
  });

  it("revokes a working key only after the dialog is confirmed", async () => {
    const user = userEvent.setup();
    let sent: FormData | undefined;
    const revokeAction = vi.fn<Action>(async (formData) => {
      sent = formData;
    });
    const { container } = render(
      <ApiKeysView
        title="API keys"
        keys={KEYS}
        crumbs={CRUMBS}
        tabs={TABS}
        revokeAction={revokeAction}
      />,
    );
    expect(screen.getAllByRole("columnheader")).toHaveLength(6);
    expect(screen.getByRole("columnheader", { name: "Actions" })).toBeDefined();
    expect(screen.getAllByRole("button", { name: /^Revoke/ }).map((b) => b.textContent)).toEqual([
      "Revoke CI deploy",
      "Revoke Tally sync",
    ]);
    expect(within(row(container, "key_old")).queryByRole("button")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(screen.getByRole("button", { name: "Revoke CI deploy" }));
    const dialog = await screen.findByRole("dialog", { name: "Revoke CI deploy?" });
    expect(dialog.textContent).toContain("Calls made with this key are refused from now on");
    expect(revokeAction).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Revoke key" }));
    await waitFor(() => expect(revokeAction).toHaveBeenCalledTimes(1));
    expect(sent?.get("key_id")).toBe("key_ci");
  });

  it("shows a new key's whole secret once, with a copy button", async () => {
    const { container } = render(
      <ApiKeysView
        title="API keys"
        keys={KEYS}
        crumbs={CRUMBS}
        tabs={TABS}
        newKey={{ name: "ERP connector", secret: "cw_live_5e6f7a8b9c0d1e2f3a4b5c6d" }}
      />,
    );
    const banner = container.querySelector("[data-slot='new-api-key']") as HTMLElement;
    expect(banner.textContent).toContain("Key created: ERP connector");
    expect(banner.textContent).toContain("this is the only time the whole key is shown");
    expect(within(banner).getByText("cw_live_5e6f7a8b9c0d1e2f3a4b5c6d")).toBeDefined();
    expect(within(banner).getByRole("button", { name: "Copy the key" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("explains an empty list and still offers the create form", async () => {
    const { container } = render(
      <ApiKeysView
        title="API keys"
        keys={[]}
        crumbs={CRUMBS}
        tabs={TABS}
        createAction={vi.fn<Action>(async () => undefined)}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No API keys" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("button", { name: "Create key" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
