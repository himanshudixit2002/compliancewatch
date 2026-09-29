import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { afterEach, describe, expect, it } from "vitest";
import { JumpToClause } from "./jump-to-clause";
import { ScrollToMarked } from "./scroll-to-marked";

afterEach(() => {
  window.location.hash = "";
});

function Clauses() {
  return (
    <>
      <p id="clause-en.p1" tabIndex={-1}>
        Example clause text one
      </p>
      <p id="clause-en.p2" tabIndex={-1}>
        Example clause text two
      </p>
    </>
  );
}

describe("JumpToClause", () => {
  it("moves the address and the focus to the chosen clause", async () => {
    const { container } = render(
      <>
        <JumpToClause
          options={[
            { anchorId: "clause-en.p1", label: "en.p1 (page 1)" },
            { anchorId: "clause-en.p2", label: "en.p2 (page 1)" },
          ]}
        />
        <Clauses />
      </>,
    );
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Clause"), "clause-en.p2");
    await user.click(screen.getByRole("button", { name: "Go to the clause" }));
    expect(window.location.hash).toBe("#clause-en.p2");
    expect(document.activeElement?.id).toBe("clause-en.p2");
    const form = screen.getByRole("form", { name: "Jump to a clause" });
    expect(await runAxe(form)).toHaveNoViolations();
    expect(container).toBeDefined();
  });

  it("renders nothing without clauses", () => {
    const { container } = render(<JumpToClause options={[]} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("ScrollToMarked", () => {
  it("brings the marked clause into view and focus when the address has no fragment", () => {
    const scrolled: string[] = [];
    Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
      scrolled.push(this.id);
    };
    render(
      <>
        <Clauses />
        <ScrollToMarked anchorId="clause-en.p2" />
      </>,
    );
    expect(scrolled).toEqual(["clause-en.p2"]);
    expect(document.activeElement?.id).toBe("clause-en.p2");
  });

  it("leaves the position to the fragment when the address has one", () => {
    const scrolled: string[] = [];
    Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
      scrolled.push(this.id);
    };
    window.location.hash = "#clause-en.p1";
    render(
      <>
        <Clauses />
        <ScrollToMarked anchorId="clause-en.p2" />
        <ScrollToMarked anchorId="clause-missing" />
      </>,
    );
    expect(scrolled).toEqual([]);
  });
});
