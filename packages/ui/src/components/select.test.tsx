import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { runAxe } from "../test/axe";
import { Select } from "./select";

const options = [
  { value: "a", label: "Option A" },
  { value: "b", label: "Option B" },
  { value: "c", label: "Option C", disabled: true },
];

describe("Select", () => {
  it("renders the options with a disabled placeholder and changes value", async () => {
    const onChange = vi.fn();
    const { container } = render(
      <Select
        aria-label="Choice"
        options={options}
        placeholder="Pick one"
        defaultValue=""
        onChange={onChange}
      />,
    );
    const select = screen.getByRole("combobox", { name: "Choice" }) as HTMLSelectElement;
    expect(select.options).toHaveLength(4);
    expect(select.options[0]?.disabled).toBe(true);
    expect(select.options[3]?.disabled).toBe(true);
    await userEvent.selectOptions(select, "b");
    expect(onChange).toHaveBeenCalled();
    expect(select.value).toBe("b");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("renders children when no options are given", () => {
    render(
      <Select aria-label="Grouped">
        <optgroup label="Group">
          <option value="x">X</option>
        </optgroup>
      </Select>,
    );
    expect(screen.getByRole("option", { name: "X" })).toBeDefined();
    expect(screen.getByRole("combobox").dataset.slot).toBe("select");
  });
});
