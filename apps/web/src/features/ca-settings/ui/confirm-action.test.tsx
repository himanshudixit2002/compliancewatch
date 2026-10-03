import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { ConfirmAction } from "./confirm-action";

type Action = (formData: FormData) => Promise<void>;

function renderAction(action: Action) {
  return render(
    <ConfirmAction
      action={action}
      fields={{ key_id: "key_1", origin: "settings" }}
      label="Revoke"
      subject="Tally sync"
      title="Revoke Tally sync?"
      description="Calls made with this key are refused from now on."
      confirmLabel="Revoke key"
    />,
  );
}

describe("ConfirmAction", () => {
  it("names the button after what it acts on and asks before sending anything", async () => {
    const user = userEvent.setup();
    const action = vi.fn<Action>(async () => undefined);
    renderAction(action);

    await user.click(screen.getByRole("button", { name: "Revoke Tally sync" }));
    const dialog = await screen.findByRole("dialog", { name: "Revoke Tally sync?" });
    expect(dialog.textContent).toContain("Calls made with this key are refused from now on.");
    expect(await runAxe(dialog)).toHaveNoViolations();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(action).not.toHaveBeenCalled();
  });

  it("sends the fields once confirmed, then closes", async () => {
    const user = userEvent.setup();
    let sent: FormData | undefined;
    const action = vi.fn<Action>(async (formData) => {
      sent = formData;
    });
    renderAction(action);

    await user.click(screen.getByRole("button", { name: "Revoke Tally sync" }));
    await user.click(await screen.findByRole("button", { name: "Revoke key" }));
    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    expect(sent?.get("key_id")).toBe("key_1");
    expect(sent?.get("origin")).toBe("settings");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
