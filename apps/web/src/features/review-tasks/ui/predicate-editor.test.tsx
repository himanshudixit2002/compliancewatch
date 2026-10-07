import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ontologyFixture } from "@/test/ontology-fixture";
import { PredicateEditor } from "./predicate-editor";
import type { EditorOntology } from "./predicate-tree";

const ONTOLOGY: EditorOntology = {
  ...ontologyFixture(),
  operatorsByType: {
    ...ontologyFixture().operatorsByType,
    decimal: ["eq", "gt"],
    date: ["eq", "gte"],
    string: ["eq", "in"],
  },
};

const STORED = {
  all_of: [{ attribute: "example_kind", operator: "eq", value: "first" }],
};

function hiddenValue(container: HTMLElement, name: string): unknown {
  const input = container.querySelector<HTMLInputElement>(`input[type='hidden'][name='${name}']`);
  return input === null ? undefined : (JSON.parse(input.value) as unknown);
}

function Harness({
  initial = STORED,
  showErrors = false,
  onProblems = () => undefined,
  error,
}: {
  initial?: unknown;
  showErrors?: boolean;
  onProblems?: (count: number) => void;
  error?: string;
}) {
  const [problems, setProblems] = useState(0);
  return (
    <form>
      <p data-testid="problems">{problems}</p>
      <PredicateEditor
        idPrefix="example"
        name="specification"
        baseName="base:specification"
        initial={initial}
        ontology={ONTOLOGY}
        disabled={false}
        showErrors={showErrors}
        {...(error === undefined ? {} : { error })}
        onProblems={(count) => {
          setProblems(count);
          onProblems(count);
        }}
      />
    </form>
  );
}

describe("PredicateEditor", () => {
  it("opens a stored condition, says it in words and posts it unchanged with its base", async () => {
    const { container } = render(<Harness />);
    expect(hiddenValue(container, "specification")).toEqual(STORED);
    expect(hiddenValue(container, "base:specification")).toEqual(STORED);
    const preview = container.querySelector("[data-slot='predicate-preview']");
    expect(preview?.textContent).toContain("All of these hold:");
    expect(preview?.textContent).toContain("example_kindis Example first kind");
    expect(screen.getByRole("combobox", { name: "Attribute" })).toHaveProperty(
      "value",
      "example_kind",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("adds a condition through the attribute's suggestions, with the operators and values of its type", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Add a condition to Group 1" }));
    const attributes = screen.getAllByRole("combobox", { name: /^Attribute/ });
    const added = attributes[1] as HTMLInputElement;
    await user.type(added, "band");
    const listbox = screen.getByRole("listbox", { name: "Attributes" });
    expect(
      within(listbox)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["example_bandExample definition of example_band."]);
    expect(added.getAttribute("aria-expanded")).toBe("true");
    await user.keyboard("{ArrowDown}");
    expect(added.getAttribute("aria-activedescendant")).toMatch(/option-0$/);
    await user.keyboard("{Enter}");
    expect(added.value).toBe("example_band");
    expect(added.getAttribute("aria-expanded")).toBe("false");

    const operators = screen.getAllByLabelText(/^Comparison/);
    const operator = operators[1] as HTMLSelectElement;
    expect([...operator.options].map((option) => option.value)).toEqual([
      "",
      "eq",
      "neq",
      "in",
      "not_in",
      "gt",
      "gte",
      "lt",
      "lte",
    ]);
    await user.selectOptions(operator, "gte");
    const values = screen.getAllByLabelText(/^Value/);
    await user.selectOptions(values[1] as HTMLSelectElement, "medium");
    expect(hiddenValue(container, "specification")).toEqual({
      all_of: [
        { attribute: "example_kind", operator: "eq", value: "first" },
        { attribute: "example_band", operator: "gte", value: "medium" },
      ],
    });
    expect(container.querySelector("[data-slot='predicate-preview']")?.textContent).toContain(
      "example_bandis at least Example medium band",
    );
    expect(screen.getByTestId("problems").textContent).toBe("0");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("nests a group, negates a part, moves and removes parts, and takes free text", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Add a group to Group 1" }));
    await user.click(screen.getByRole("button", { name: "Add a condition to Group 1.2" }));
    const attribute = screen.getAllByRole("combobox", {
      name: /^Attribute/,
    })[1] as HTMLInputElement;
    await user.type(attribute, "example_unknown");
    await user.keyboard("{Escape}");
    await user.type(
      screen.getAllByLabelText(/^Needs judgement/)[1] as HTMLTextAreaElement,
      "Example judgement",
    );
    await user.click(screen.getByRole("button", { name: "Part 1.1 must not hold" }));
    expect(hiddenValue(container, "specification")).toEqual({
      all_of: [
        { not: { attribute: "example_kind", operator: "eq", value: "first" } },
        { any_of: [{ attribute: "example_unknown", free_text: "Example judgement" }] },
      ],
    });
    await user.click(screen.getByRole("button", { name: "Move part 1.2 up" }));
    expect(hiddenValue(container, "specification")).toMatchObject({
      all_of: [{ any_of: [{ attribute: "example_unknown" }] }, { not: {} }],
    });
    await user.click(screen.getByRole("button", { name: "Remove the negation of part 1.2" }));
    await user.click(screen.getByRole("button", { name: "Remove part 1.1" }));
    expect(hiddenValue(container, "specification")).toEqual({
      all_of: [{ attribute: "example_kind", operator: "eq", value: "first" }],
    });
  });

  it("counts the shape problems and shows each on its field once the form asks", async () => {
    const user = userEvent.setup();
    const onProblems = vi.fn();
    const { rerender } = render(<Harness onProblems={onProblems} />);
    await user.click(screen.getByRole("button", { name: "Add a condition to Group 1" }));
    expect(screen.getByTestId("problems").textContent).toBe("2");
    expect(screen.queryByText("Choose an attribute.")).toBeNull();
    rerender(<Harness onProblems={onProblems} showErrors />);
    const attribute = screen.getAllByRole("combobox", {
      name: /^Attribute/,
    })[1] as HTMLInputElement;
    expect(attribute.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Choose an attribute.")).toBeDefined();
    expect(
      screen.getByText("Choose an operator and a value, or write what has to be judged."),
    ).toBeDefined();
  });

  it("edits the condition as JSON, refusing a shape the kernel does not read", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);
    await user.click(screen.getByRole("button", { name: "JSON" }));
    const text = screen.getByLabelText(/^The condition as JSON/) as HTMLTextAreaElement;
    expect(JSON.parse(text.value)).toEqual(STORED);
    await user.clear(text);
    await user.click(text);
    await user.paste('{"all_of": {}}');
    expect(screen.getByTestId("problems").textContent).toBe("1");
    await user.click(screen.getByRole("button", { name: "Use this JSON" }));
    expect(screen.getByText("specification.all_of must be a list.")).toBeDefined();
    expect(text.getAttribute("aria-invalid")).toBe("true");
    await user.clear(text);
    await user.click(text);
    await user.paste(
      '{"any_of": [{"attribute": "example_flag", "operator": "eq", "value": true}]}',
    );
    await user.click(screen.getByRole("button", { name: "Use this JSON" }));
    expect(hiddenValue(container, "specification")).toEqual({
      any_of: [{ attribute: "example_flag", operator: "eq", value: true }],
    });
    expect(screen.getByLabelText(/^This group holds when/)).toHaveProperty("value", "any_of");
    await user.click(screen.getByRole("button", { name: "JSON" }));
    await user.click(screen.getByRole("button", { name: "Back to the builder without it" }));
    expect(screen.getByTestId("problems").textContent).toBe("0");
  });

  it("combines a single stored condition with another, and shows the rulebook's message", async () => {
    const user = userEvent.setup();
    const single = { attribute: "example_flag", operator: "eq", value: false };
    const { container } = render(<Harness initial={single} error="Example rulebook message" />);
    expect(screen.getByRole("alert").textContent).toBe("Example rulebook message");
    await user.click(screen.getByRole("button", { name: "Combine with another condition" }));
    expect(hiddenValue(container, "specification")).toEqual({
      all_of: [single, { attribute: "", free_text: "" }],
    });
  });
});

describe("PredicateEditor with a part it cannot read", () => {
  it("says so and writes the part back as stored", () => {
    const { container } = render(<Harness initial={{ all_of: [{ example: 1 }] }} />);
    expect(container.querySelector("[data-slot='raw-part']")?.textContent).toContain(
      '{"example":1}',
    );
    expect(hiddenValue(container, "specification")).toEqual({ all_of: [{ example: 1 }] });
  });
});
