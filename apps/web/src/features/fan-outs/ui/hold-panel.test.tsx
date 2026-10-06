import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { HoldPanel } from "./hold-panel";
import type { ControlAction } from "./use-control";

const HELD = {
  ok: true as const,
  hold: {
    held: true,
    reason: "Example deploy of the rulebook",
    by: "user 00000000…",
    since: "6 Jan 2000, 10:00 am IST",
  },
};
const OFF = { ok: true as const, hold: { held: false, reason: null, by: null, since: null } };

function recorder(answer: Awaited<ReturnType<ControlAction>>) {
  const sent: Record<string, string>[] = [];
  const action = vi.fn<ControlAction>(async (_state, formData) => {
    sent.push(Object.fromEntries([...formData.entries()].map(([k, v]) => [k, String(v)])));
    return answer;
  });
  return { action, sent };
}

describe("HoldPanel", () => {
  it("leads with a danger banner naming the reason, who set it and when, while it is set", async () => {
    const { container } = render(
      <HoldPanel hold={HELD} canControl={false} action={vi.fn<ControlAction>()} />,
    );
    const banner = screen.getByRole("alert");
    expect(banner.textContent).toContain("Every fan-out is on hold");
    expect(banner.textContent).toContain("Why: Example deploy of the rulebook");
    expect(banner.textContent).toContain("Set by user 00000000… on 6 Jan 2000, 10:00 am IST.");
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("Only an admin sets or releases the hold.")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("lets an admin set the hold with a reason of ten characters, and says it is set", async () => {
    const { action, sent } = recorder({
      status: "ok",
      value: { message: "The hold is set: example." },
      message: "The hold is set: example.",
    });
    const { container } = render(<HoldPanel hold={OFF} canControl action={action} />);
    expect(screen.getByText("No hold is set: fan-outs run as rules are published.")).toBeDefined();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Hold every fan-out" }));
    const dialog = screen.getByRole("dialog", { name: "Hold every fan-out?" });
    const confirm = within(dialog).getByRole("button", { name: "Hold every fan-out" });
    await user.type(within(dialog).getByRole("textbox"), "Too short");
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    await user.type(within(dialog).getByRole("textbox"), " but now enough");
    await user.click(confirm);
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("The hold is set: example."),
    );
    expect(sent).toEqual([{ sent: "hold", hold: "on", reason: "Too short but now enough" }]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("releases the hold with a reason and shows a refusal with its correlation id", async () => {
    const { action, sent } = recorder({
      status: "error",
      problem: {
        type: "urn:compliancewatch:problem:test-503",
        title: "Example engine unavailable",
        correlationId: "req-example-9",
      },
    });
    render(<HoldPanel hold={HELD} canControl action={action} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Release the hold" }));
    const dialog = screen.getByRole("dialog", { name: "Release the hold?" });
    await user.type(within(dialog).getByRole("textbox"), "Example deploy finished");
    await user.click(within(dialog).getByRole("button", { name: "Release the hold" }));
    await waitFor(() => expect(screen.getByText("Example engine unavailable")).toBeDefined());
    expect(screen.getByText("req-example-9")).toBeDefined();
    expect(sent).toEqual([{ sent: "release", hold: "off", reason: "Example deploy finished" }]);
  });

  it("says the hold could not be read, with the correlation id", async () => {
    const { container } = render(
      <HoldPanel
        hold={{ ok: false, failure: { message: "Example down", correlationId: "req-example-1" } }}
        canControl
        action={vi.fn<ControlAction>()}
      />,
    );
    expect(screen.getByText("The hold could not be read")).toBeDefined();
    expect(screen.getByText("req-example-1")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says when no reason and no setter were recorded", () => {
    render(
      <HoldPanel
        hold={{ ok: true, hold: { held: true, reason: null, by: null, since: null } }}
        canControl
        action={vi.fn<ControlAction>()}
      />,
    );
    expect(screen.getByText("No reason was given.")).toBeDefined();
    expect(screen.queryByText(/Set by/)).toBeNull();
  });
});
