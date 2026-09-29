import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Button } from "./button";
import { EmptyState } from "./empty-state";

describe("EmptyState", () => {
  it("renders the title as an h2 with the reason and an action", async () => {
    const { container } = render(
      <EmptyState
        title="No items"
        body="Nothing has been recorded."
        action={<Button>Add</Button>}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No items" })).toBeDefined();
    expect(screen.getByText("Nothing has been recorded.")).toBeDefined();
    expect(screen.getByRole("button", { name: "Add" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("takes a custom heading level and icon", () => {
    render(<EmptyState heading="h3" title="Empty" icon={<svg data-testid="icon" />} />);
    expect(screen.getByRole("heading", { level: 3, name: "Empty" })).toBeDefined();
    expect(screen.getByTestId("icon")).toBeDefined();
  });
});
