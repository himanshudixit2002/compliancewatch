import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { runAxe } from "../test/axe";
import { CopyButton } from "./copy-button";

function stubClipboard(writeText: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
}

describe("CopyButton", () => {
  afterEach(() => {
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
  });

  it("writes the value to the clipboard and announces it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    const { container } = render(<CopyButton value="abc-123" label="Copy id" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy id" }));
    expect(writeText).toHaveBeenCalledWith("abc-123");
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Copied"));
    expect(screen.getByRole("button").dataset.state).toBe("copied");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("reports a failure instead of throwing", async () => {
    stubClipboard(vi.fn().mockRejectedValue(new Error("denied")));
    render(<CopyButton value="x" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Copy failed"));
  });
});
