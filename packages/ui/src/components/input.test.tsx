import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Input } from "./input";

describe("Input", () => {
  it("renders a text input by default and accepts typing", async () => {
    const { container } = render(<Input aria-label="Trade name" />);
    const input = screen.getByRole("textbox", { name: "Trade name" });
    expect(input.getAttribute("type")).toBe("text");
    await userEvent.type(input, "Example");
    expect((input as HTMLInputElement).value).toBe("Example");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("passes type, invalid state and extra classes through", () => {
    render(<Input type="email" aria-label="Email" aria-invalid className="w-40" />);
    const input = screen.getByRole("textbox", { name: "Email" });
    expect(input.getAttribute("type")).toBe("email");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.className).toContain("w-40");
    expect(input.dataset.slot).toBe("input");
  });
});
