import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { IDEMPOTENCY_KEY_FIELD } from "@/shared/lib/idempotency";
import { AssigneePanel, type AssigneeMode } from "./assignee-panel";
import type { TrackingAction } from "./tracking-form";
import { TRACKING_FIELDS } from "./tracking-shared";

const VIEWER = "00000000-0000-4000-8000-0000000000ab";
const COLLEAGUE = "00000000-0000-4000-8000-0000000000ac";
const KEY = "00000000-0000-4000-8000-00000000c0c2";

function fields(formData: FormData): Record<string, string> {
  return Object.fromEntries([...formData.entries()].map(([key, value]) => [key, String(value)]));
}

function renderPanel(
  action: TrackingAction,
  mode: AssigneeMode,
  assigneeId: string | null = null,
  open = true,
) {
  return render(
    <AssigneePanel
      action={action}
      businessId="00000000-0000-4000-8000-0000000000e1"
      obligationId="00000000-0000-4000-8000-0000000000b1"
      idempotencyKey={KEY}
      assigneeId={assigneeId}
      assigneeText={assigneeId === null ? "Nobody" : "Example colleague"}
      viewerId={VIEWER}
      mode={mode}
      open={open}
    />,
  );
}

describe("AssigneePanel", () => {
  it("lets an admin pick one of the tenant's users", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<TrackingAction>(async (_state, formData) => {
      sent.push(fields(formData));
      return { status: "ok", value: { message: "Example given.", replayed: false } };
    });
    const { container } = renderPanel(action, {
      kind: "members",
      options: [{ id: COLLEAGUE, label: "Example colleague (Staff)" }],
    });
    expect(screen.getByText("It is given to nobody.")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Give it to"), COLLEAGUE);
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Example given."));
    expect(sent[0]).toMatchObject({
      [TRACKING_FIELDS.assignee]: COLLEAGUE,
      [IDEMPOTENCY_KEY_FIELD]: KEY,
    });
  });

  it("keeps an assignee the list does not hold as a choice", () => {
    renderPanel(vi.fn<TrackingAction>(), { kind: "members", options: [] }, COLLEAGUE);
    const select = screen.getByLabelText("Give it to") as HTMLSelectElement;
    expect(select.value).toBe(COLLEAGUE);
    expect(screen.getByText("It is given to Example colleague.")).toBeDefined();
  });

  it("offers an id field, giving it to me or to nobody, with the reason", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<TrackingAction>(async (_state, formData) => {
      sent.push(fields(formData));
      return {
        status: "error",
        fieldErrors: { [TRACKING_FIELDS.assignee]: ["Example field error"] },
      };
    });
    const { container } = renderPanel(
      action,
      { kind: "id", note: "Example reason for an id field." },
      COLLEAGUE,
    );
    expect(screen.getByText("Example reason for an id field.")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Give it to me" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]?.[TRACKING_FIELDS.assignTo]).toBe("me");
    expect(await screen.findByText("Example field error")).toBeDefined();
    await user.click(screen.getByRole("button", { name: "Give it to nobody" }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]?.[TRACKING_FIELDS.assignTo]).toBe("nobody");
  });

  it("changes nothing on a closed obligation", () => {
    renderPanel(vi.fn<TrackingAction>(), { kind: "id", note: "x" }, null, false);
    expect(screen.getByText("A closed obligation keeps who it was given to.")).toBeDefined();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
