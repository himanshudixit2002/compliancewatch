import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Textarea } from "./textarea";

describe("Textarea", () => {
  it("renders a multi-line control that accepts text", async () => {
    const { container } = render(<Textarea aria-label="Note" />);
    const textarea = screen.getByRole("textbox", { name: "Note" });
    expect(textarea.tagName).toBe("TEXTAREA");
    await userEvent.type(textarea, "line one{Enter}line two");
    expect((textarea as HTMLTextAreaElement).value).toBe("line one\nline two");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("passes invalid state and classes through", () => {
    render(<Textarea aria-label="Note" aria-invalid className="h-20" />);
    const textarea = screen.getByRole("textbox", { name: "Note" });
    expect(textarea.getAttribute("aria-invalid")).toBe("true");
    expect(textarea.className).toContain("h-20");
  });
});
