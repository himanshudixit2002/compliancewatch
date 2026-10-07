import { Component, type ReactNode } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { IDEMPOTENCY_KEY_FIELD } from "@/shared/lib/idempotency";
import { StatusPanel } from "./status-panel";
import type { TrackingAction } from "./tracking-form";

const KEY = "00000000-0000-4000-8000-00000000c0c1";
const ACTIONS = [
  { action: "start" as const, label: "Start work" },
  { action: "complete" as const, label: "Mark as done" },
  { action: "waive" as const, label: "Waive" },
];

function sentFields(formData: FormData): Record<string, string> {
  return Object.fromEntries([...formData.entries()].map(([key, value]) => [key, String(value)]));
}

function renderPanel(action: TrackingAction, actions = ACTIONS) {
  return render(
    <StatusPanel
      action={action}
      businessId="00000000-0000-4000-8000-0000000000e1"
      obligationId="00000000-0000-4000-8000-0000000000b1"
      idempotencyKey={KEY}
      actions={actions}
      title="Example return 1"
    />,
  );
}

describe("StatusPanel", () => {
  it("starts at once and completes after the dialog, with the render's key each time", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<TrackingAction>(async (_state, formData) => {
      sent.push(sentFields(formData));
      return {
        status: "ok",
        value: { message: "Example done.", replayed: false },
        message: "Example done.",
      };
    });
    const { container } = renderPanel(action);
    expect(await runAxe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Start work" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Example done."));
    await user.click(screen.getByRole("button", { name: "Mark as done" }));
    const dialog = await screen.findByRole("dialog", { name: "Mark this obligation as done?" });
    expect(dialog.textContent).toContain("“Example return 1” closes as done");
    await user.click(within(dialog).getByRole("button", { name: "Mark as done" }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent.map((fields) => fields.action)).toEqual(["start", "complete"]);
    expect(sent.every((fields) => fields[IDEMPOTENCY_KEY_FIELD] === KEY)).toBe(true);
  });

  it("asks a waiver for its reason and sends it", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<TrackingAction>(async (_state, formData) => {
      sent.push(sentFields(formData));
      return { status: "ok", value: { message: "Example waived.", replayed: false } };
    });
    renderPanel(action);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Waive" }));
    const dialog = await screen.findByRole("dialog", { name: "Waive this obligation?" });
    const confirm = within(dialog).getByRole("button", { name: "Waive" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    await user.type(within(dialog).getByRole("textbox"), "Example reason for waiving");
    await user.click(confirm);
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Example waived."));
    expect(sent[0]).toMatchObject({ action: "waive", reason: "Example reason for waiving" });
  });

  it("keeps a request whose answer was lost and sends exactly it again", async () => {
    const sent: Record<string, string>[] = [];
    let calls = 0;
    const action = vi.fn<TrackingAction>(async (_state, formData) => {
      sent.push(sentFields(formData));
      calls += 1;
      if (calls === 1) throw new TypeError("Failed to fetch");
      return {
        status: "ok",
        value: { message: "Example done. Example replayed.", replayed: true },
      };
    });
    renderPanel(action);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Start work" }));
    expect(await screen.findByText("No answer arrived")).toBeDefined();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("Example done. Example replayed."),
    );
    expect(sent).toHaveLength(2);
    expect(sent[1]).toEqual(sent[0]);
  });

  it("shows a refusal with its correlation id, and a closed obligation offers nothing", async () => {
    const action = vi.fn<TrackingAction>(async () => ({
      status: "error",
      problem: {
        type: "urn:compliancewatch:problem:obligation-closed",
        title: "Example obligation closed",
        correlationId: "req-example-2",
      },
      formErrors: ["Example form message"],
    }));
    const { unmount } = renderPanel(action);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Start work" }));
    expect(await screen.findByText("Example obligation closed")).toBeDefined();
    expect(screen.getByText("req-example-2")).toBeDefined();
    expect(screen.getByText("Example form message").getAttribute("role")).toBe("alert");
    unmount();
    renderPanel(action, []);
    expect(screen.getByText(/This obligation is closed/)).toBeDefined();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("lets a redirect from the server through to the framework", async () => {
    // React reports the error the boundary caught; the boundary is the test's, so is the report.
    const reported = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const redirect = Object.assign(new Error("NEXT_REDIRECT"), {
      digest: "NEXT_REDIRECT;push;/sign-in",
    });
    const action = vi.fn<TrackingAction>(async () => {
      throw redirect;
    });
    const caught: unknown[] = [];
    class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
      override state = { failed: false };
      static getDerivedStateFromError() {
        return { failed: true };
      }
      override componentDidCatch(error: unknown) {
        caught.push(error);
      }
      override render() {
        return this.state.failed ? <p>Example boundary</p> : this.props.children;
      }
    }
    render(
      <Boundary>
        <StatusPanel
          action={action}
          businessId="00000000-0000-4000-8000-0000000000e1"
          obligationId="00000000-0000-4000-8000-0000000000b1"
          idempotencyKey={KEY}
          actions={ACTIONS}
          title="Example return 1"
        />
      </Boundary>,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Start work" }));
    expect(await screen.findByText("Example boundary")).toBeDefined();
    expect(caught).toEqual([redirect]);
    reported.mockRestore();
  });
});
