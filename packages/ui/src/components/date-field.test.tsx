import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { DateField } from "./date-field";

describe("DateField", () => {
  it("is the browser's date input with its bounds, label and description", async () => {
    const { container } = render(
      <DateField
        id="since"
        label="Example date"
        description="The day it started."
        name="value"
        min="2000-01-01"
        max="2000-12-31"
        defaultValue="2000-06-15"
      />,
    );
    const input = screen.getByLabelText("Example date") as HTMLInputElement;
    expect(input.type).toBe("date");
    expect(input.min).toBe("2000-01-01");
    expect(input.max).toBe("2000-12-31");
    expect(input.value).toBe("2000-06-15");
    expect(input.name).toBe("value");
    expect(input.getAttribute("aria-describedby")).toBe("since-description");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("marks the input invalid with the error", async () => {
    const { container } = render(
      <DateField id="d" label="Example day" error="Enter a date." required />,
    );
    const input = screen.getByLabelText(/Example day/);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-required")).toBe("true");
    expect(screen.getByText("Enter a date.").id).toBe("d-error");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
