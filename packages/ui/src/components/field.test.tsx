import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Field } from "./field";
import { Input } from "./input";

describe("Field", () => {
  it("wires the label, description and control together", async () => {
    const { container } = render(
      <Field id="gstin" label="GSTIN" description="Fifteen characters" required>
        <Input />
      </Field>,
    );
    const input = screen.getByLabelText(/GSTIN/);
    expect(input.id).toBe("gstin");
    expect(input.getAttribute("aria-describedby")).toBe("gstin-description");
    expect(input.getAttribute("aria-invalid")).toBeNull();
    expect(input.getAttribute("aria-required")).toBe("true");
    expect(screen.getByText("Fifteen characters").id).toBe("gstin-description");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("marks the control invalid and describes it by the error", async () => {
    const { container } = render(
      <Field id="email" label="Email" error={["Enter an email address.", "Must be unique."]}>
        <Input type="email" />
      </Field>,
    );
    const input = screen.getByLabelText("Email");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")).toBe("email-error");
    const error = screen.getByText("Enter an email address. Must be unique.");
    expect(error.id).toBe("email-error");
    expect(container.querySelector('[data-slot="field"]')?.getAttribute("data-invalid")).toBe(
      "true",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("accepts a single error string and has no describedby when nothing describes it", () => {
    const { rerender } = render(
      <Field id="name" label="Name" error="Required.">
        <Input />
      </Field>,
    );
    expect(screen.getByText("Required.").id).toBe("name-error");
    rerender(
      <Field id="name" label="Name">
        <Input />
      </Field>,
    );
    expect(screen.getByLabelText("Name").getAttribute("aria-describedby")).toBeNull();
  });
});
