import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { lifecycleFromDto } from "@/entities/rule-version/mappers";
import { EXAMPLE_ANALYST_ID, lifecycleDto } from "@/test/rule-version-fixture";
import { WorkflowPanel, type TakeStepAction, type WorkflowPanelProps } from "./workflow-panel";

function renderPanel(action: TakeStepAction, props: Partial<WorkflowPanelProps> = {}) {
  return render(
    <WorkflowPanel
      action={action}
      steps={["submit"]}
      reserved={[]}
      access={{ allowed: true }}
      version={1}
      highImpact={false}
      sessionUserId={EXAMPLE_ANALYST_ID}
      sessionName="Example analyst"
      {...props}
    />,
  );
}

describe("WorkflowPanel", () => {
  it("submits as high impact with a note after the dialog, and shows the new round", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<TakeStepAction>(async (_state, formData) => {
      sent.push(Object.fromEntries([...formData.entries()].map(([k, v]) => [k, String(v)])));
      return {
        status: "ok",
        value: {
          step: "submit",
          lifecycle: lifecycleFromDto(lifecycleDto({ approved_by: [] })),
          publication: null,
        },
      };
    });
    const { container } = renderPanel(action);
    expect(await runAxe(container)).toHaveNoViolations();
    expect(screen.getByText(/version read does not carry them yet/)).toBeDefined();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Submit for review" }));
    const dialog = screen.getByRole("dialog", { name: "Submit for review: version 1" });
    expect(dialog.textContent).toContain("starts a new review round");
    await user.click(within(dialog).getByRole("checkbox"));
    await user.type(within(dialog).getByLabelText(/Note/), "Example note");
    await user.click(within(dialog).getByRole("button", { name: "Submit for review" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain(
        "Submitted for review as high impact",
      ),
    );
    expect(sent).toEqual([{ step: "submit", note: "Example note", high_impact: "on" }]);
    expect(screen.getByText("0 of 2 approvals in this round.")).toBeDefined();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("names the approvers so far, says a second is needed, and shows a refusal under its step", async () => {
    let calls = 0;
    const action = vi.fn<TakeStepAction>(async () => {
      calls += 1;
      if (calls === 1) {
        return {
          status: "ok",
          value: {
            step: "approve",
            lifecycle: lifecycleFromDto(lifecycleDto()),
            publication: null,
          },
        };
      }
      return {
        status: "error",
        problem: {
          type: "urn:compliancewatch:problem:rulebook-duplicate-approver",
          title: "Example approver already approved",
          detail: "Example detail",
          correlationId: "req-example-3",
        },
      };
    });
    const { container } = renderPanel(action, { steps: ["approve", "return"], highImpact: true });
    expect(screen.getByText(/This one is high impact/)).toBeDefined();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(screen.getByText("Example analyst (you)")).toBeDefined());
    expect(screen.getByRole("status").textContent).toContain(
      "1 of 2 approvals in this round. It needs a second approver: a different reviewer or admin.",
    );
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("req-example-3"));
    const step = container.querySelector('[data-step="approve"]') as HTMLElement;
    expect(within(step).getByText("Example approver already approved")).toBeDefined();
    // The approvals the rulebook reported stay on the page.
    expect(screen.getByText("Example analyst (you)")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("asks for a reason of ten characters before a return, and sends it as the note", async () => {
    const sent: string[] = [];
    const action = vi.fn<TakeStepAction>(async (_state, formData) => {
      sent.push(String(formData.get("note")));
      return {
        status: "ok",
        value: {
          step: "return",
          lifecycle: lifecycleFromDto(lifecycleDto({ status: "draft", approved_by: [] })),
          publication: null,
        },
      };
    });
    renderPanel(action, { steps: ["approve", "return"] });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Return to draft" }));
    const dialog = screen.getByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Return to draft" });
    await user.type(within(dialog).getByRole("textbox"), "Too short");
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    await user.type(within(dialog).getByRole("textbox"), " a reason");
    await user.click(confirm);
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("Returned to draft"),
    );
    expect(sent).toEqual(["Too short a reason"]);
    expect(screen.queryByText(/approvals in this round/)).toBeNull();
  });

  it("holds every step back with the refusal while access is refused, and lists no step when none is left", () => {
    const { rerender } = renderPanel(vi.fn<TakeStepAction>(), {
      access: {
        allowed: false,
        title: "Example flag is off",
        detail: "Example detail",
        flag: "web.publish_actions",
      },
    });
    expect(screen.getByText("Example flag is off")).toBeDefined();
    expect(
      (screen.getByRole("button", { name: "Submit for review" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    rerender(
      <WorkflowPanel
        action={vi.fn<TakeStepAction>()}
        steps={[]}
        reserved={[]}
        access={{ allowed: true }}
        version={2}
        highImpact={false}
        sessionUserId={EXAMPLE_ANALYST_ID}
        sessionName="Example analyst"
      />,
    );
    expect(screen.getByText(/No further step/)).toBeDefined();
  });

  it("names the steps left to a reviewer or an admin and offers none of them", async () => {
    const { container } = renderPanel(vi.fn<TakeStepAction>(), {
      steps: ["return"],
      reserved: ["approve"],
    });
    expect(container.querySelector("[data-slot='workflow-reserved']")?.textContent).toBe(
      "Approving, publishing and withdrawing are a reviewer's or an admin's. Not offered to you here: Approve.",
    );
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.getByRole("button", { name: "Return to draft" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
    renderPanel(vi.fn<TakeStepAction>(), { steps: [], reserved: ["withdraw"] });
    expect(screen.queryByText(/No further step/)).toBeNull();
  });

  it("shows a check of the step form as a message under the step", async () => {
    renderPanel(
      vi.fn<TakeStepAction>(async () => ({
        status: "error",
        fieldErrors: { note: ["Example note error"] },
      })),
      { steps: ["publish"] },
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Publish" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Example note error"));
  });
});
