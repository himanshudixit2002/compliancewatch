import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { attributeOf } from "@/entities/ontology/mappers";
import type { OntologyAttribute } from "@/entities/ontology/types";
import { ontologyFixture } from "@/test/ontology-fixture";
import { AttributeControl } from "./attribute-control";

const ontology = ontologyFixture();

function attribute(key: string): OntologyAttribute {
  const found = attributeOf(ontology, key);
  if (found === undefined) throw new Error(`fixture has no ${key}`);
  return found;
}

/** Renders the control inside a form and returns what the form would submit. */
function renderInForm(ui: React.ReactElement) {
  const result = render(<form aria-label="Example form">{ui}</form>);
  const form = result.container.querySelector("form") as HTMLFormElement;
  return { ...result, submitted: (name = "value") => new FormData(form).getAll(name) };
}

describe("AttributeControl", () => {
  it("asks an enum as radio buttons in the ontology's order, labelled by the question", async () => {
    const user = userEvent.setup();
    const kind = attribute("example_kind");
    const { container, submitted } = renderInForm(
      <AttributeControl
        attribute={kind}
        id="kind"
        label={kind.question}
        description={kind.help}
        defaultValue="first"
      />,
    );
    const group = screen.getByRole("radiogroup", { name: "Example question about example_kind?" });
    expect(group.getAttribute("aria-describedby")).toBe("kind-description");
    expect(
      screen.getAllByRole("radio").map((radio) => radio.getAttribute("aria-label") ?? radio.id),
    ).toEqual(["kind-first", "kind-second"]);
    expect(submitted()).toEqual(["first"]);
    await user.click(screen.getByRole("radio", { name: "Example second kind" }));
    expect(submitted()).toEqual(["second"]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("asks an ordered band the same way and marks an error", async () => {
    const band = attribute("example_band");
    const { container } = renderInForm(
      <AttributeControl attribute={band} id="band" label="Example band" error="Choose one." />,
    );
    const group = screen.getByRole("radiogroup", { name: "Example band" });
    expect(group.getAttribute("aria-invalid")).toBe("true");
    expect(group.getAttribute("aria-describedby")).toBe("band-error");
    expect(screen.getByText("Choose one.").id).toBe("band-error");
    expect(screen.getAllByRole("radio").map((radio) => radio.id)).toEqual([
      "band-small",
      "band-medium",
      "band-large",
    ]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("asks a boolean as Yes and No", async () => {
    const user = userEvent.setup();
    const { submitted } = renderInForm(
      <AttributeControl attribute={attribute("example_flag")} id="flag" label="Example flag" />,
    );
    expect(submitted()).toEqual([]);
    await user.click(screen.getByRole("radio", { name: "No" }));
    expect(submitted()).toEqual(["false"]);
    expect(screen.getByRole("radio", { name: "Yes" })).toBeDefined();
  });

  it("asks a set as a checkbox group whose ticked boxes all submit", async () => {
    const user = userEvent.setup();
    const { container, submitted } = renderInForm(
      <AttributeControl
        attribute={attribute("state_codes")}
        id="places"
        label="Example places"
        defaultValue={["02"]}
      />,
    );
    expect(screen.getByRole("group", { name: "Example places" })).toBeDefined();
    await user.click(screen.getByRole("checkbox", { name: "Example place one" }));
    expect(submitted()).toEqual(["01", "02"]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("takes a single suggested value for a set", () => {
    const { submitted } = renderInForm(
      <AttributeControl
        attribute={attribute("state_codes")}
        id="p"
        label="Example places"
        defaultValue="03"
      />,
    );
    expect(submitted()).toEqual(["03"]);
  });

  it("asks a whole number with its range, and a decimal with the decimal keyboard", async () => {
    const { container, rerender } = render(
      <AttributeControl
        attribute={attribute("example_count")}
        id="count"
        label="Example count"
        defaultValue="12"
      />,
    );
    const input = screen.getByRole("textbox", { name: "Example count" }) as HTMLInputElement;
    expect(input.value).toBe("12");
    expect(input.getAttribute("inputmode")).toBe("numeric");
    expect(screen.getByText("Between 0 and 1,000.")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
    rerender(
      <AttributeControl attribute={attribute("example_ratio")} id="ratio" label="Example ratio" />,
    );
    expect(screen.getByRole("textbox", { name: "Example ratio" }).getAttribute("inputmode")).toBe(
      "decimal",
    );
  });

  it("asks a date with the date input and a string with a text input", async () => {
    const { container, rerender } = render(
      <AttributeControl
        attribute={attribute("example_since")}
        id="since"
        label="Example since"
        defaultValue="2000-01-01"
      />,
    );
    const date = screen.getByLabelText("Example since") as HTMLInputElement;
    expect(date.type).toBe("date");
    expect(date.value).toBe("2000-01-01");
    expect(await runAxe(container)).toHaveNoViolations();
    rerender(
      <AttributeControl
        attribute={attribute("example_note")}
        id="note"
        label="Example note"
        defaultValue="Example"
        disabled
      />,
    );
    const text = screen.getByRole("textbox", { name: "Example note" }) as HTMLInputElement;
    expect(text.value).toBe("Example");
    expect(text.disabled).toBe(true);
  });

  it("keeps the label for screen readers only when a heading asks the question", () => {
    const { container, rerender } = render(
      <AttributeControl attribute={attribute("example_kind")} id="k" label="Example" hideLabel />,
    );
    expect(container.querySelector("#k-label")?.className).toContain("sr-only");
    rerender(
      <AttributeControl attribute={attribute("example_count")} id="c" label="Example" hideLabel />,
    );
    expect(screen.getByRole("textbox", { name: "Example" })).toBeDefined();
    expect(container.querySelector("label .sr-only")?.textContent).toBe("Example");
  });
});
