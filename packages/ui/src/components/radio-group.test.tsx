import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { runAxe } from "../test/axe";
import { Label } from "./label";
import { RadioGroup, RadioGroupItem } from "./radio-group";

describe("RadioGroup", () => {
  it("moves the selection with the arrow keys", async () => {
    const onValueChange = vi.fn();
    const { container } = render(
      <RadioGroup aria-label="Filing" defaultValue="monthly" onValueChange={onValueChange}>
        <div className="flex gap-2">
          <RadioGroupItem value="monthly" id="monthly" />
          <Label htmlFor="monthly">Monthly</Label>
        </div>
        <div className="flex gap-2">
          <RadioGroupItem value="quarterly" id="quarterly" />
          <Label htmlFor="quarterly">Quarterly</Label>
        </div>
      </RadioGroup>,
    );
    expect(screen.getByRole("radiogroup", { name: "Filing" })).toBeDefined();
    const monthly = screen.getByRole("radio", { name: "Monthly" });
    expect(monthly.getAttribute("aria-checked")).toBe("true");
    await userEvent.tab();
    expect(document.activeElement).toBe(monthly);
    // Radix moves focus in a timeout after keydown and checks the item while the key is held.
    await userEvent.keyboard("{ArrowDown>}");
    await userEvent.keyboard("{/ArrowDown}");
    expect(onValueChange).toHaveBeenCalledWith("quarterly");
    expect(screen.getByRole("radio", { name: "Quarterly" }).getAttribute("aria-checked")).toBe(
      "true",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
