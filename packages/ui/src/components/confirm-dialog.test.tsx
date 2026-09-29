import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { runAxe } from "../test/axe";
import { Button } from "./button";
import { ConfirmDialog } from "./confirm-dialog";

describe("ConfirmDialog", () => {
  it("opens from its trigger, explains what is recorded and confirms", async () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        trigger={<Button>Close task</Button>}
        title="Close this task?"
        description="Records closed_by as your user id."
        confirmLabel="Close task"
        onConfirm={onConfirm}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Close task" }));
    const dialog = screen.getByRole("dialog", { name: "Close this task?" });
    expect(dialog.textContent).toContain("Records closed_by as your user id.");
    expect(dialog.dataset.destructive).toBeUndefined();
    expect(await runAxe(dialog)).toHaveNoViolations();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Close task" }));
    await userEvent.click(
      screen.getByRole("dialog").querySelector('[data-slot="confirm"]') as HTMLElement,
    );
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("uses the danger button when destructive and disables everything while pending", () => {
    render(
      <ConfirmDialog open title="Delete?" destructive pending onConfirm={() => {}}>
        <p>Body</p>
      </ConfirmDialog>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog.dataset.destructive).toBe("true");
    const confirm = dialog.querySelector('[data-slot="confirm"]') as HTMLButtonElement;
    expect(confirm.dataset.variant).toBe("danger");
    expect(confirm.getAttribute("aria-busy")).toBe("true");
    expect(confirm.disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(screen.getByText("Body")).toBeDefined();
  });
});
