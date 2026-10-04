import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { DocumentsOpenView } from "./documents-open-view";

type Action = (state: ActionState, formData: FormData) => Promise<ActionState>;

const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.rulebook.documents", href: "/admin/rulebook/documents", label: "Documents" },
];

function renderView(action: Action) {
  return render(
    <DocumentsOpenView title="Documents" crumbs={CRUMBS} action={action} field="document_id" />,
  );
}

describe("DocumentsOpenView", () => {
  it("asks for an id or a sha256 and says where a list will come from", async () => {
    const { container } = renderView(vi.fn<Action>(async () => ({ status: "idle" })));
    expect(screen.getByRole("heading", { level: 1, name: "Documents" })).toBeDefined();
    expect(screen.getByLabelText(/Document id or sha256/)).toBeDefined();
    expect(container.textContent).toContain("arrives with the source manager");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("sends what was typed, keeps it after a refusal, and focuses the field with its error", async () => {
    let sent: string | undefined;
    renderView(
      vi.fn<Action>(async (_state, formData) => {
        sent = String(formData.get("document_id"));
        return {
          status: "error",
          fieldErrors: { document_id: ["The rulebook holds no document with this id."] },
        };
      }),
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Document id or sha256/), "example-id");
    await user.click(screen.getByRole("button", { name: "Open the document" }));
    await waitFor(() =>
      expect(screen.getByText("The rulebook holds no document with this id.")).toBeDefined(),
    );
    expect(sent).toBe("example-id");
    const input = screen.getByLabelText(/Document id or sha256/) as HTMLInputElement;
    expect(input.value).toBe("example-id");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(input);
  });

  it("shows the service's problem with its reference and focuses it", async () => {
    const { container } = renderView(
      vi.fn<Action>(async () => ({
        status: "error",
        problem: {
          type: "urn:compliancewatch:problem:test-503",
          title: "Rulebook unavailable",
          correlationId: "req-example-3",
        },
      })),
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Document id or sha256/), "x");
    await user.click(screen.getByRole("button", { name: "Open the document" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("req-example-3"));
    expect(container.contains(document.activeElement)).toBe(true);
    expect(document.activeElement?.contains(screen.getByRole("alert"))).toBe(true);
  });
});
