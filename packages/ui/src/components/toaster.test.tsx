import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Toaster, toast } from "./toaster";

describe("Toaster", () => {
  it("renders a polite live region that shows queued toasts", async () => {
    const { container } = render(<Toaster />);
    const region = container.querySelector("[aria-live]");
    expect(region?.getAttribute("aria-live")).toBe("polite");
    act(() => {
      toast.success("Saved");
    });
    expect(await screen.findByText("Saved")).toBeDefined();
    expect(container.querySelector("[data-sonner-toast]")?.getAttribute("data-type")).toBe(
      "success",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("points sonner's colour variables at the tokens", async () => {
    const { container } = render(<Toaster />);
    act(() => {
      toast("Example");
    });
    await screen.findByText("Example");
    const list = container.querySelector("[data-sonner-toaster]") as HTMLElement;
    expect(list.style.getPropertyValue("--normal-bg")).toBe("var(--surface-raised)");
    expect(list.style.getPropertyValue("--error-bg")).toBe("var(--danger)");
  });
});
