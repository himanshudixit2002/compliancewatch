import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { ConsentChange } from "./consent-change";

const FIELDS = { purpose: "purpose", change: "change", number: "whatsapp_number" };

type Action = (state: ActionState<string>, formData: FormData) => Promise<ActionState<string>>;

function renderChange(action: Action, withNumber = false) {
  return render(
    <ConsentChange
      action={action}
      purpose="whatsapp_reminders"
      purposeLabel="Example reminders"
      change="withdraw"
      statement="Example statement."
      records="Example record description."
      fields={FIELDS}
      {...(withNumber
        ? { number: { defaultValue: "+910000000000", required: false, help: "Example help." } }
        : {})}
    />,
  );
}

describe("ConsentChange", () => {
  it("opens a dialog that says what is recorded and shows the sentence confirmed", async () => {
    const user = userEvent.setup();
    renderChange(
      vi.fn<Action>(async () => ({ status: "idle" })),
      true,
    );
    const trigger = screen.getByRole("button", { name: "Withdraw: Example reminders" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Withdraw Example reminders?" });
    expect(dialog.textContent).toContain("Example record description.");
    expect(dialog.textContent).toContain("Example statement.");
    const number = screen.getByLabelText(/WhatsApp number/) as HTMLInputElement;
    expect(number.value).toBe("+910000000000");
    expect(await runAxe(dialog)).toHaveNoViolations();
  });

  it("sends the purpose, the change and the number, then closes and says what was recorded", async () => {
    const user = userEvent.setup();
    let sent: FormData | undefined;
    const action = vi.fn<Action>(async (_state, formData) => {
      sent = formData;
      return { status: "ok", value: "done", message: "Example recorded message." };
    });
    renderChange(action, true);
    await user.click(screen.getByRole("button", { name: "Withdraw: Example reminders" }));
    await user.click(await screen.findByRole("button", { name: "Withdraw" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("Example recorded message."),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(sent?.get("purpose")).toBe("whatsapp_reminders");
    expect(sent?.get("change")).toBe("withdraw");
    expect(sent?.get("whatsapp_number")).toBe("+910000000000");
  });

  it("moves focus to the status line once the page shows the flipped change", async () => {
    const user = userEvent.setup();
    const action = vi.fn<Action>(async () => ({ status: "ok", message: "Example recorded." }));
    const props = {
      action,
      purpose: "analytics",
      purposeLabel: "Example analytics",
      statement: "Example statement.",
      records: "Example record description.",
      fields: FIELDS,
    };
    const { rerender } = render(<ConsentChange {...props} change="give" />);
    await user.click(screen.getByRole("button", { name: "Give consent: Example analytics" }));
    await user.click(await screen.findByRole("button", { name: "Agree" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Example recorded."));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    rerender(<ConsentChange {...props} change="withdraw" />);
    expect(screen.getByRole("button", { name: "Withdraw: Example analytics" })).toBeDefined();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("status")));
    rerender(<ConsentChange {...props} change="withdraw" />);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("status")));
  });

  it("keeps the dialog open with the problem and the field to fix after a refusal", async () => {
    const user = userEvent.setup();
    const action = vi.fn<Action>(async () => ({
      status: "error",
      problem: { type: "urn:example", title: "Example problem", correlationId: "req-1" },
      fieldErrors: { whatsapp_number: ["Example field error."] },
      formErrors: ["Example form error."],
    }));
    renderChange(action, true);
    await user.click(screen.getByRole("button", { name: "Withdraw: Example reminders" }));
    await user.click(await screen.findByRole("button", { name: "Withdraw" }));
    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    const dialog = screen.getByRole("dialog");
    // The refusal renders after the action resolves, which can lag the call on a slow runner.
    await waitFor(() => expect(dialog.textContent).toContain("Example problem"));
    expect(dialog.textContent).toContain("req-1");
    expect(dialog.textContent).toContain("Example field error.");
    expect(dialog.textContent).toContain("Example form error.");
    expect(screen.getByRole("status").textContent).toBe("");
    // Enter in the number field submits the dialog's form the same way.
    fireEvent.submit(dialog.querySelector("form") as HTMLFormElement);
    await waitFor(() => expect(action).toHaveBeenCalledTimes(2));
  });

  it("gives with the primary button and no number field when none applies", async () => {
    const user = userEvent.setup();
    render(
      <ConsentChange
        action={vi.fn<Action>(async () => ({ status: "idle" }))}
        purpose="analytics"
        purposeLabel="Example analytics"
        change="give"
        statement="Example statement."
        records="Example record description."
        fields={FIELDS}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Give consent: Example analytics" }));
    await screen.findByRole("dialog", { name: "Give consent to Example analytics?" });
    expect(screen.getByRole("button", { name: "Agree" })).toBeDefined();
    expect(screen.queryByLabelText(/WhatsApp number/)).toBeNull();
  });
});
