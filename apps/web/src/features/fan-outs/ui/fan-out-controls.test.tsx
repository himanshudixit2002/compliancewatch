import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { FanOutControls } from "./fan-out-controls";
import type { ControlAction } from "./use-control";

function recorder() {
  const sent: Record<string, string>[] = [];
  const action = vi.fn<ControlAction>(async (_state, formData) => {
    sent.push(Object.fromEntries([...formData.entries()].map(([k, v]) => [k, String(v)])));
    const control = String(formData.get("control"));
    return { status: "ok", value: { message: `Example ${control} done` } };
  });
  return { action, sent };
}

describe("FanOutControls", () => {
  it("pauses with a reason, and says what it did where focus lands", async () => {
    const { action, sent } = recorder();
    const { container } = render(
      <FanOutControls
        controls={["pause", "cancel"]}
        canControl
        name="example_rule v2"
        action={action}
      />,
    );
    expect(await runAxe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Pause" }));
    const dialog = screen.getByRole("dialog", { name: "Pause the fan-out of example_rule v2?" });
    expect(dialog.textContent).toContain("releasing the global hold does not restart it");
    await user.type(within(dialog).getByRole("textbox"), "Example flips look wrong");
    await user.click(within(dialog).getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Example pause done"));
    expect(sent).toEqual([{ sent: "pause", control: "pause", reason: "Example flips look wrong" }]);
    expect(document.activeElement?.getAttribute("data-slot")).toBe("control-outcome");
  });

  it("cancels in a destructive dialog that says the decisions stay", async () => {
    const { action, sent } = recorder();
    render(
      <FanOutControls
        controls={["resume", "cancel"]}
        canControl
        name="example_rule v2"
        action={action}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Cancel the run" }));
    const dialog = screen.getByRole("dialog", { name: "Cancel the fan-out of example_rule v2?" });
    expect(dialog.textContent).toContain("The decisions it made stay");
    expect(dialog.getAttribute("data-destructive")).toBe("true");
    await user.type(within(dialog).getByRole("textbox"), "Example wrong threshold");
    await user.click(within(dialog).getByRole("button", { name: "Cancel the run" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ control: "cancel", reason: "Example wrong threshold" });
  });

  it("resumes with an optional reason", async () => {
    const { action, sent } = recorder();
    render(
      <FanOutControls
        controls={["resume", "cancel"]}
        canControl
        name="example_rule v2"
        action={action}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Resume" }));
    const dialog = screen.getByRole("dialog", { name: "Resume the fan-out of example_rule v2?" });
    await user.type(
      within(dialog).getByLabelText(/Reason \(optional\)/),
      "  Example looked again  ",
    );
    await user.click(within(dialog).getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({ sent: "resume", control: "resume", reason: "Example looked again" });
  });

  it("shows a refusal with the field's message", async () => {
    const action = vi.fn<ControlAction>(async () => ({
      status: "error",
      fieldErrors: { reason: ["Example reason refused"] },
    }));
    render(
      <FanOutControls controls={["pause"]} canControl name="example_rule v2" action={action} />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Pause" }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByRole("textbox"), "Example long enough reason");
    await user.click(within(dialog).getByRole("button", { name: "Pause" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe("Example reason refused"),
    );
  });

  it("offers nothing to anyone but an admin, and nothing once the run has finished", async () => {
    const { container, rerender } = render(
      <FanOutControls
        controls={["pause"]}
        canControl={false}
        name="x"
        action={vi.fn<ControlAction>()}
      />,
    );
    expect(screen.getByText("Only an admin pauses, resumes or cancels a fan-out.")).toBeDefined();
    expect(screen.queryByRole("button")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
    rerender(<FanOutControls controls={[]} canControl name="x" action={vi.fn<ControlAction>()} />);
    expect(screen.getByText(/This run has finished/)).toBeDefined();
  });
});
