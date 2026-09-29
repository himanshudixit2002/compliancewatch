import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { runAxe } from "../test/axe";
import { CheckboxGroup } from "./checkbox-group";

const OPTIONS = [
  { value: "one", label: "Example one" },
  { value: "two", label: "Example two", description: "Example hint for two" },
  { value: "three", label: "Example three", disabled: true },
];

describe("CheckboxGroup", () => {
  it("groups the boxes under the legend and toggles them with the keyboard", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    const { container } = render(
      <CheckboxGroup
        id="places"
        legend="Example places"
        description="Tick every one that applies."
        name="value"
        options={OPTIONS}
        defaultValue={["two"]}
        onValueChange={onValueChange}
        required
        columns={2}
      />,
    );
    const group = screen.getByRole("group", { name: /Example places/ });
    expect(group.getAttribute("aria-describedby")).toBe("places-description");
    expect(screen.getByText("(required)")).toBeDefined();
    const two = screen.getByRole("checkbox", { name: "Example two" });
    expect(two.getAttribute("aria-checked")).toBe("true");
    expect(two.getAttribute("aria-describedby")).toBe("places-two-description");
    expect(screen.getByRole("checkbox", { name: "Example three" }).hasAttribute("disabled")).toBe(
      true,
    );
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("checkbox", { name: "Example one" }));
    await user.keyboard(" ");
    // The values keep the options' order, not the order they were ticked in.
    expect(onValueChange).toHaveBeenLastCalledWith(["one", "two"]);
    await user.click(two);
    expect(onValueChange).toHaveBeenLastCalledWith(["one"]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("submits every checked value under the name", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <form>
        <CheckboxGroup id="picks" legend="Example picks" name="pick" options={OPTIONS} />
      </form>,
    );
    await user.click(screen.getByRole("checkbox", { name: "Example two" }));
    await user.click(screen.getByRole("checkbox", { name: "Example one" }));
    const form = container.querySelector("form") as HTMLFormElement;
    expect(new FormData(form).getAll("pick")).toEqual(["one", "two"]);
  });

  it("follows a controlled value and shows the error", async () => {
    const { container, rerender } = render(
      <CheckboxGroup
        id="c"
        legend="Example controlled"
        name="c"
        options={OPTIONS}
        value={[]}
        error={["Choose at least one."]}
      />,
    );
    const group = screen.getByRole("group", { name: "Example controlled" });
    expect(group.getAttribute("aria-invalid")).toBe("true");
    expect(group.getAttribute("aria-describedby")).toBe("c-error");
    expect(screen.getByText("Choose at least one.").id).toBe("c-error");
    expect(await runAxe(container)).toHaveNoViolations();
    rerender(
      <CheckboxGroup
        id="c"
        legend="Example controlled"
        name="c"
        options={OPTIONS}
        value={["one"]}
      />,
    );
    expect(screen.getByRole("checkbox", { name: "Example one" }).getAttribute("aria-checked")).toBe(
      "true",
    );
    expect(group.getAttribute("aria-invalid")).toBeNull();
  });

  it("disables every box when the group is disabled", () => {
    render(<CheckboxGroup id="d" legend="Example disabled" name="d" options={OPTIONS} disabled />);
    for (const box of screen.getAllByRole("checkbox")) {
      expect(box.hasAttribute("disabled")).toBe(true);
    }
  });
});
