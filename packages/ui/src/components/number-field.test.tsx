import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { NumberField, rangeText } from "./number-field";

describe("rangeText", () => {
  it("says the range in words with Indian digit grouping", () => {
    expect(rangeText(0, 100000)).toBe("Between 0 and 1,00,000.");
    expect(rangeText(1, null)).toBe("At least 1.");
    expect(rangeText(undefined, 10)).toBe("At most 10.");
    expect(rangeText(null, null)).toBeNull();
  });
});

describe("NumberField", () => {
  it("is a text input with the numeric keyboard, described by its range", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <NumberField id="count" label="Example count" name="value" min={0} max={1000} required />,
    );
    const input = screen.getByRole("textbox", { name: /Example count/ });
    expect(input.getAttribute("type")).toBe("text");
    expect(input.getAttribute("inputmode")).toBe("numeric");
    expect(input.getAttribute("name")).toBe("value");
    expect(input.getAttribute("aria-describedby")).toBe("count-description");
    expect(screen.getByText("Between 0 and 1,000.").id).toBe("count-description");
    await user.type(input, "12");
    expect((input as HTMLInputElement).value).toBe("12");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("joins a description with the range, takes decimals and shows the error", async () => {
    const { container } = render(
      <NumberField
        id="ratio"
        label="Example ratio"
        description="Example description."
        integer={false}
        min={1}
        error="Enter a number."
        defaultValue="1.5"
      />,
    );
    const input = screen.getByRole("textbox", { name: "Example ratio" });
    expect(input.getAttribute("inputmode")).toBe("decimal");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")).toBe("ratio-description ratio-error");
    expect(screen.getByText("Example description. At least 1.")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("uses the caller's hint, or none", () => {
    const { rerender } = render(
      <NumberField id="n" label="Example n" min={0} rangeHint="Example hint." />,
    );
    expect(screen.getByText("Example hint.")).toBeDefined();
    rerender(<NumberField id="n" label="Example n" min={0} rangeHint={null} />);
    expect(screen.getByRole("textbox").getAttribute("aria-describedby")).toBeNull();
    rerender(<NumberField id="n" label="Example n" description="Only this." />);
    expect(screen.getByText("Only this.")).toBeDefined();
  });
});
