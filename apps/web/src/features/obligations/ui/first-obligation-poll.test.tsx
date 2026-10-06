import { act, render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FirstObligationPoll } from "./first-obligation-poll";
import type { FirstObligationState } from "./tracking-shared";

const FOUND: FirstObligationState = {
  status: "found",
  title: "Example return 1",
  due: "20 Jan 2000",
  dueNote: "Due in 10 days",
  href: "/b/x/obligations/y",
};

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

async function advance(seconds: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(seconds * 1000);
  });
}

describe("FirstObligationPoll", () => {
  it("shows the first obligation at once when the page already found it", async () => {
    const check = vi.fn(async () => FOUND);
    vi.useRealTimers();
    const { container } = render(
      <FirstObligationPoll check={check} initial={FOUND} listHref="/b/x/obligations" />,
    );
    expect(screen.getByRole("link", { name: "Example return 1" }).getAttribute("href")).toBe(
      "/b/x/obligations/y",
    );
    expect(screen.getByRole("status").textContent).toContain(
      "The first obligation, due 20 Jan 2000:",
    );
    expect(check).not.toHaveBeenCalled();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("checks every few seconds until the first obligation appears", async () => {
    const answers: FirstObligationState[] = [
      { status: "none" },
      { status: "error", message: "Example unavailable", correlationId: "req-example-4" },
      FOUND,
    ];
    const check = vi.fn(async () => answers.shift() ?? FOUND);
    render(
      <FirstObligationPoll
        check={check}
        initial={{ status: "none" }}
        listHref="/b/x/obligations"
        intervalSeconds={3}
      />,
    );
    expect(screen.getByRole("status").textContent).toContain("This page checks every 3 seconds");
    await advance(3);
    expect(check).toHaveBeenCalledTimes(1);
    await advance(3);
    expect(screen.getByText("Example unavailable")).toBeDefined();
    expect(screen.getByText("req-example-4")).toBeDefined();
    await advance(3);
    expect(screen.getByRole("link", { name: "Example return 1" })).toBeDefined();
    await advance(9);
    expect(check).toHaveBeenCalledTimes(3);
  });

  it("stops after the timeout with an honest note, and checks again on request", async () => {
    const check = vi.fn(async (): Promise<FirstObligationState> => ({ status: "none" }));
    render(
      <FirstObligationPoll
        check={check}
        initial={{ status: "none" }}
        listHref="/b/x/obligations"
        intervalSeconds={3}
        timeoutSeconds={9}
      />,
    );
    await advance(9);
    expect(screen.getByText("No obligation yet")).toBeDefined();
    expect(screen.getByRole("status").textContent).toContain("Nothing has appeared in 9 seconds.");
    const calls = check.mock.calls.length;
    await advance(9);
    expect(check.mock.calls.length).toBe(calls);
    await act(async () => {
      screen.getByRole("button", { name: "Check again" }).click();
    });
    expect(screen.getByRole("status").textContent).toContain("checks every 3 seconds");
    await advance(3);
    expect(check.mock.calls.length).toBe(calls + 1);
  });

  it("says when the web server could not be reached and keeps checking", async () => {
    const check = vi.fn(async (): Promise<FirstObligationState> => {
      throw new TypeError("Failed to fetch");
    });
    render(
      <FirstObligationPoll
        check={check}
        initial={{ status: "none" }}
        listHref="/b/x/obligations"
      />,
    );
    await advance(3);
    expect(screen.getByText(/could not be reached to check/)).toBeDefined();
    expect(screen.getByRole("link", { name: "Open the obligations page" })).toBeDefined();
  });
});
