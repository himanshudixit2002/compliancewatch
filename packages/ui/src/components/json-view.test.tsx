import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { JsonView } from "./json-view";

describe("JsonView", () => {
  it("renders nested values as collapsible details, open to the given depth", async () => {
    const { container } = render(
      <JsonView
        value={{
          name: "Example",
          tags: ["a", "b"],
          nested: { deep: { deeper: null } },
          ok: true,
          n: 1,
        }}
        openDepth={1}
      />,
    );
    const pre = container.querySelector("pre");
    expect(pre?.getAttribute("aria-label")).toBe("JSON");
    const details = container.querySelectorAll("details");
    expect(details[0]?.getAttribute("data-kind")).toBe("object");
    expect(details[0]?.hasAttribute("open")).toBe(true);
    const tags = container.querySelector('details[data-kind="array"]');
    expect(tags?.hasAttribute("open")).toBe(false);
    expect(tags?.querySelector("summary")?.textContent).toBe("tags: array (2)");
    expect(screen.getByText('"Example"').dataset.kind).toBe("string");
    expect(screen.getByText("null").dataset.kind).toBe("null");
    expect(screen.getByText("true").dataset.kind).toBe("boolean");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("renders a scalar root", () => {
    const { container } = render(<JsonView value={42} label="Answer" />);
    expect(container.querySelector("pre")?.textContent).toBe("42");
    expect(container.querySelector("pre")?.getAttribute("aria-label")).toBe("Answer");
  });
});
