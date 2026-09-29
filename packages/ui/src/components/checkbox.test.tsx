import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { runAxe } from "../test/axe";
import { Checkbox } from "./checkbox";
import { Label } from "./label";

describe("Checkbox", () => {
  it("toggles with the keyboard and reports the change", async () => {
    const onCheckedChange = vi.fn();
    const { container } = render(
      <div className="flex gap-2">
        <Checkbox id="agree" onCheckedChange={onCheckedChange} />
        <Label htmlFor="agree">I agree</Label>
      </div>,
    );
    const box = screen.getByRole("checkbox", { name: "I agree" });
    expect(box.getAttribute("aria-checked")).toBe("false");
    await userEvent.tab();
    await userEvent.keyboard(" ");
    expect(onCheckedChange).toHaveBeenCalledWith(true);
    expect(box.getAttribute("aria-checked")).toBe("true");
    expect(box.dataset.state).toBe("checked");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("renders a controlled checked state and can be disabled", () => {
    render(<Checkbox aria-label="Done" checked disabled />);
    const box = screen.getByRole("checkbox", { name: "Done" });
    expect(box.getAttribute("aria-checked")).toBe("true");
    expect(box.hasAttribute("disabled")).toBe(true);
    expect(box.dataset.slot).toBe("checkbox");
  });
});
