import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Input } from "./input";
import { Label } from "./label";

describe("Label", () => {
  it("labels a control through htmlFor", async () => {
    const { container } = render(
      <>
        <Label htmlFor="gstin">GSTIN</Label>
        <Input id="gstin" />
      </>,
    );
    const input = screen.getByLabelText("GSTIN");
    expect(input.id).toBe("gstin");
    expect(screen.getByText("GSTIN").dataset.slot).toBe("label");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
