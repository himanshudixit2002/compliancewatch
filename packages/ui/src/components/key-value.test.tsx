import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { KeyValue } from "./key-value";

describe("KeyValue", () => {
  it("renders a description list with an optional copy button", async () => {
    const { container } = render(
      <KeyValue
        items={[
          { key: "id", label: "Identifier", value: "abc", copy: "abc" },
          { key: "state", label: "State", value: "Example" },
          { key: "node", label: <em>Node</em>, value: "n-1", copy: "n-1" },
          {
            key: "ref",
            label: <em>Ref</em>,
            value: "r-1",
            copy: "r-1",
            copyLabel: "Copy reference",
          },
        ]}
      />,
    );
    const list = container.querySelector("dl");
    expect(list?.dataset.slot).toBe("key-value");
    expect(list?.className).toContain("sm:grid-cols-[max-content_1fr]");
    expect(screen.getAllByRole("term")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Copy Identifier" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Copy" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Copy reference" })).toBeDefined();
    expect(screen.getAllByRole("button")).toHaveLength(3);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("stacks label over value when asked", () => {
    const { container } = render(
      <KeyValue layout="stack" items={[{ key: "a", label: "A", value: "1" }]} />,
    );
    expect(container.querySelector("dl")?.className).toContain("grid-cols-1");
  });
});
