import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { IDEMPOTENCY_KEY_FIELD } from "@/shared/lib/idempotency";
import { CommentForm } from "./comment-form";
import type { TrackingAction } from "./tracking-form";
import { TRACKING_FIELDS } from "./tracking-shared";

const KEY = "00000000-0000-4000-8000-00000000c0c3";

function renderForm(action: TrackingAction) {
  return render(
    <CommentForm
      action={action}
      businessId="00000000-0000-4000-8000-0000000000e1"
      obligationId="00000000-0000-4000-8000-0000000000b1"
      idempotencyKey={KEY}
    />,
  );
}

describe("CommentForm", () => {
  it("sends the comment with the render's key and says it was added", async () => {
    const sent: FormData[] = [];
    const action = vi.fn<TrackingAction>(async (_state, formData) => {
      sent.push(formData);
      return { status: "ok", value: { message: "Comment added.", replayed: false } };
    });
    const { container } = renderForm(action);
    expect(await runAxe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Comment/), "Example comment");
    await user.click(screen.getByRole("button", { name: "Add the comment" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Comment added."));
    expect(sent[0]?.get(TRACKING_FIELDS.body)).toBe("Example comment");
    expect(sent[0]?.get(IDEMPOTENCY_KEY_FIELD)).toBe(KEY);
  });

  it("shows a refusal on the field", async () => {
    const action = vi.fn<TrackingAction>(async () => ({
      status: "error",
      fieldErrors: { [TRACKING_FIELDS.body]: ["Write the comment first."] },
    }));
    renderForm(action);
    await userEvent.setup().click(screen.getByRole("button", { name: "Add the comment" }));
    expect(await screen.findByText("Write the comment first.")).toBeDefined();
  });
});
