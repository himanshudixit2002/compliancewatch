import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { ResolvePanel, type ResolveAction } from "./resolve-panel";

describe("ResolvePanel", () => {
  it("settles the item with a result and a note after the dialog says what follows", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<ResolveAction>(async (_state, formData) => {
      sent.push(Object.fromEntries([...formData.entries()].map(([k, v]) => [k, String(v)])));
      return { status: "ok", value: { message: "Example settled." }, message: "Example settled." };
    });
    const { container } = render(<ResolvePanel action={action} versionName="example_rule v2" />);
    expect(await runAxe(container)).toHaveNoViolations();
    const submit = screen.getByRole("button", { name: "Settle the item" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "It does not apply" }));
    await user.type(screen.getByLabelText(/^Note/), "  Example reason it does not apply  ");
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    await user.click(submit);
    const dialog = await screen.findByRole("dialog", {
      name: "Settle the review item of example_rule v2?",
    });
    expect(dialog.textContent).toContain("closes the obligations it made");
    await user.click(within(dialog).getByRole("button", { name: "Settle the item" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Example settled."));
    expect(sent).toEqual([
      { resolution: "not_applicable", note: "Example reason it does not apply" },
    ]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the engine's refusal and a field's message", async () => {
    const action = vi
      .fn<ResolveAction>()
      .mockResolvedValueOnce({
        status: "error",
        problem: {
          type: "urn:compliancewatch:problem:applicability-review-item-resolved",
          title: "Example already resolved",
          correlationId: "req-example-5",
        },
      })
      .mockResolvedValueOnce({ status: "error", fieldErrors: { note: ["Example note refused"] } });
    render(<ResolvePanel action={action} versionName="example_rule v2" />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "Dismissed, with no decision" }));
    await user.type(screen.getByLabelText(/^Note/), "Example note");
    await user.click(screen.getByRole("button", { name: "Settle the item" }));
    expect((await screen.findByRole("dialog")).textContent).toContain("nothing is appended");
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Settle the item" }),
    );
    await waitFor(() => expect(screen.getByText("Example already resolved")).toBeDefined());
    expect(screen.getByText("req-example-5")).toBeDefined();
    await user.click(screen.getByRole("button", { name: "Settle the item" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Settle the item" }),
    );
    await waitFor(() => expect(screen.getByText("Example note refused")).toBeDefined());
  });
});
