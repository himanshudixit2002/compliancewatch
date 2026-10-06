import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { EXAMPLE_OTHER_VERSION_ID, EXAMPLE_VERSION_ID } from "@/test/rule-version-fixture";
import { CandidateDecisions, type CandidateAction } from "./candidate-decisions";

const OPTIONS = {
  from: [{ value: EXAMPLE_VERSION_ID, label: "example_rule v2 (Draft): Example title" }],
  target: [
    { value: EXAMPLE_OTHER_VERSION_ID, label: "example_rule v1 (Published): Example title" },
  ],
};

function sentOf(formData: FormData): Record<string, string> {
  return Object.fromEntries([...formData.entries()].map(([key, value]) => [key, String(value)]));
}

function renderPanel(
  overrides: Partial<Parameters<typeof CandidateDecisions>[0]> = {},
): ReturnType<typeof render> {
  return render(
    <CandidateDecisions
      approve={vi.fn<CandidateAction>()}
      reject={vi.fn<CandidateAction>()}
      open
      statusLabel="Open"
      name="Extends deadline: Form EXAMPLE-1"
      needsTarget
      aligned={false}
      options={OPTIONS}
      optionsError={null}
      {...overrides}
    />,
  );
}

describe("CandidateDecisions", () => {
  it("approves from the draft onto the version after the dialog says what is written", async () => {
    const sent: Record<string, string>[] = [];
    const approve = vi.fn<CandidateAction>(async (_state, formData) => {
      sent.push(sentOf(formData));
      return {
        status: "ok",
        message: "Example approved.",
        value: {
          message: "Example approved.",
          ruleRelationId: "relation-1",
          graphHref: "/admin/rulebook/relations/graph?rule_version_id=example",
        },
      };
    });
    const { container } = renderPanel({ approve });
    expect(await runAxe(container)).toHaveNoViolations();
    const submit = screen.getByRole("button", { name: "Approve the candidate" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    const user = userEvent.setup();
    await user.selectOptions(
      screen.getByLabelText(/^The draft it starts from/),
      EXAMPLE_VERSION_ID,
    );
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    await user.selectOptions(
      screen.getByLabelText(/^The version it points at/),
      EXAMPLE_OTHER_VERSION_ID,
    );
    await user.click(submit);
    const dialog = screen.getByRole("dialog", {
      name: "Approve Extends deadline: Form EXAMPLE-1?",
    });
    expect(dialog.textContent).toContain(
      "from example_rule v2 (Draft): Example title to example_rule v1 (Published): Example title",
    );
    await user.click(within(dialog).getByRole("button", { name: "Approve the candidate" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("Example approved."),
    );
    expect(sent).toEqual([
      {
        from_rule_version_id: EXAMPLE_VERSION_ID,
        target_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
        note: "",
      },
    ]);
    expect(
      screen.getByRole("link", { name: "Open the relations graph around the draft" }),
    ).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("rejects with a reason and shows the rulebook's refusal", async () => {
    const sent: Record<string, string>[] = [];
    const reject = vi.fn<CandidateAction>(async (_state, formData) => {
      sent.push(sentOf(formData));
      return {
        status: "error",
        problem: {
          type: "urn:compliancewatch:problem:rulebook-relation-candidate-closed",
          title: "Example candidate closed",
          correlationId: "req-example-3",
        },
      };
    });
    renderPanel({ reject });
    const user = userEvent.setup();
    const submit = screen.getByRole("button", { name: "Reject the candidate" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    await user.selectOptions(screen.getByLabelText(/^Why reject/), "duplicate");
    await user.type(screen.getAllByLabelText(/^Note/)[1] as HTMLElement, "Example note");
    await user.click(submit);
    const dialog = screen.getByRole("dialog", { name: "Reject Extends deadline: Form EXAMPLE-1?" });
    expect(dialog.textContent).toContain("rejected (A duplicate)");
    await user.click(within(dialog).getByRole("button", { name: "Reject the candidate" }));
    await waitFor(() => expect(screen.getByText("Example candidate closed")).toBeDefined());
    expect(screen.getByText("req-example-3")).toBeDefined();
    expect(sent).toEqual([{ reason: "duplicate", note: "Example note" }]);
  });

  it("lets an aligned target go without a version, and says when no draft exists", async () => {
    const sent: Record<string, string>[] = [];
    const approve = vi.fn<CandidateAction>(async (_state, formData) => {
      sent.push(sentOf(formData));
      return { status: "error", fieldErrors: { from_rule_version_id: ["Example refused"] } };
    });
    const { unmount } = renderPanel({ approve, needsTarget: false, aligned: true });
    expect(
      screen.getByText("Optional: without one the relation points at the aligned entity."),
    ).toBeDefined();
    const user = userEvent.setup();
    await user.selectOptions(
      screen.getByLabelText(/^The draft it starts from/),
      EXAMPLE_VERSION_ID,
    );
    await user.click(screen.getByRole("button", { name: "Approve the candidate" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("to the aligned entity");
    await user.click(within(dialog).getByRole("button", { name: "Approve the candidate" }));
    await waitFor(() => expect(screen.getByText("Example refused")).toBeDefined());
    expect(sent).toEqual([{ from_rule_version_id: EXAMPLE_VERSION_ID, note: "" }]);
    unmount();

    renderPanel({ options: { from: [], target: [] } });
    expect(
      screen.getByText("No open draft version exists, so nothing can take this relation yet."),
    ).toBeDefined();
  });

  it("shows why the versions are missing, and only a note once the candidate is decided", async () => {
    const { unmount } = renderPanel({
      options: null,
      optionsError: { title: "Example versions outage", correlationId: "req-example-4" },
    });
    expect(screen.getByText("Example versions outage")).toBeDefined();
    unmount();
    const { container } = renderPanel({ open: false, statusLabel: "Approved" });
    expect(
      screen.getByText("This candidate is Approved: it takes no further decision."),
    ).toBeDefined();
    expect(screen.queryByRole("button")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
