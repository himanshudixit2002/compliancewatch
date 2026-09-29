import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { runAxe } from "../test/axe";
import { ReasonDialog } from "./reason-dialog";

describe("ReasonDialog", () => {
  it("keeps confirm disabled under ten characters, shows the error on blur, then submits the reason", async () => {
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <ReasonDialog
        open
        onOpenChange={onOpenChange}
        title="Reject candidate"
        confirmLabel="Reject"
        destructive
        onConfirm={onConfirm}
      />,
    );
    const dialog = screen.getByRole("dialog", { name: "Reject candidate" });
    const confirm = dialog.querySelector('[data-slot="confirm"]') as HTMLButtonElement;
    const reason = screen.getByLabelText(/Reason/) as HTMLTextAreaElement;
    expect(confirm.disabled).toBe(true);
    expect(reason.getAttribute("aria-required")).toBe("true");
    await userEvent.type(reason, "too short");
    expect(confirm.disabled).toBe(true);
    await userEvent.tab();
    expect(screen.getByText("Enter at least 10 characters.")).toBeDefined();
    expect(reason.getAttribute("aria-invalid")).toBe("true");
    await userEvent.type(reason, " but now long enough  ");
    expect(reason.getAttribute("aria-invalid")).toBeNull();
    expect(confirm.disabled).toBe(false);
    expect(await runAxe(dialog)).toHaveNoViolations();
    await userEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledWith("too short but now long enough");
    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows a custom label, hint and minimum", () => {
    render(
      <ReasonDialog
        open
        title="Why?"
        label="Note"
        hint="Recorded on the decision."
        minLength={3}
        onConfirm={() => {}}
      />,
    );
    expect(screen.getByLabelText(/Note/)).toBeDefined();
    expect(screen.getByText("Recorded on the decision.")).toBeDefined();
  });
});
