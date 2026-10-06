import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { RollbackPanel } from "./rollback-panel";
import type { ControlAction } from "./use-control";

describe("RollbackPanel", () => {
  it("warns what a withdrawal does, asks for a reason, and sends it", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<ControlAction>(async (_state, formData) => {
      sent.push(Object.fromEntries([...formData.entries()].map(([k, v]) => [k, String(v)])));
      return { status: "ok", value: { message: "Example withdrawn." } };
    });
    const { container } = render(
      <RollbackPanel
        rollback={{ state: "offered", access: { allowed: true } }}
        name="example_rule v2"
        action={action}
      />,
    );
    const warning = screen.getByText("Rolling back withdraws the version for every tenant");
    expect(warning.closest("[data-slot='rollback-warning']")?.textContent).toContain(
      "closes every open obligation the version made, in every tenant",
    );
    expect(await runAxe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Roll back this version" }));
    const dialog = screen.getByRole("dialog", { name: "Roll back example_rule v2?" });
    expect(dialog.textContent).toContain("It cannot be undone.");
    expect(dialog.getAttribute("data-destructive")).toBe("true");
    const confirm = within(dialog).getByRole("button", { name: "Withdraw the version" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    await user.type(within(dialog).getByRole("textbox"), "Example wrong due date");
    await user.click(confirm);
    await waitFor(() => expect(screen.getByText("Example withdrawn.")).toBeDefined());
    expect(screen.getByText("Example withdrawn.").getAttribute("role")).toBe("status");
    expect(sent).toEqual([{ sent: "rollback", reason: "Example wrong due date" }]);
  });

  it("shows the rulebook's refusal with its correlation id", async () => {
    const action = vi.fn<ControlAction>(async () => ({
      status: "error",
      problem: {
        type: "urn:compliancewatch:problem:rulebook-invalid-transition",
        title: "Example version is not published",
        correlationId: "req-example-7",
      },
    }));
    render(
      <RollbackPanel
        rollback={{ state: "offered", access: { allowed: true } }}
        name="example_rule v2"
        action={action}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Roll back this version" }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByRole("textbox"), "Example wrong due date");
    await user.click(within(dialog).getByRole("button", { name: "Withdraw the version" }));
    await waitFor(() => expect(screen.getByText("Example version is not published")).toBeDefined());
    expect(screen.getByText("req-example-7")).toBeDefined();
  });

  it("offers no button while the flag or the token refuses, and says which", async () => {
    const { container } = render(
      <RollbackPanel
        rollback={{
          state: "offered",
          access: {
            allowed: false,
            title: "The web.publish_actions flag is off",
            detail: "Example detail",
          },
        }}
        name="example_rule v2"
        action={vi.fn<ControlAction>()}
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("The web.publish_actions flag is off")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says why there is no rollback: not an admin, not published, version unknown", () => {
    const { rerender } = render(
      <RollbackPanel rollback={{ state: "not_admin" }} name="x" action={vi.fn<ControlAction>()} />,
    );
    expect(screen.getByText("Only an admin rolls a version back.")).toBeDefined();
    rerender(
      <RollbackPanel
        rollback={{ state: "not_published", statusLabel: "Draft" }}
        name="x"
        action={vi.fn<ControlAction>()}
      />,
    );
    expect(
      screen.getByText("Only a published version can be rolled back. This one is Draft."),
    ).toBeDefined();
    rerender(
      <RollbackPanel
        rollback={{ state: "unknown_version" }}
        name="x"
        action={vi.fn<ControlAction>()}
      />,
    );
    expect(screen.getByText(/could not say what this version is/)).toBeDefined();
  });
});
