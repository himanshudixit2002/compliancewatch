import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { CATALOGUE_SECTIONS, Catalogue } from "./catalogue";
import { FORBIDDEN_TOKENS } from "./fixtures.test";

describe("Catalogue", () => {
  it("renders every group under one heading, free of regulatory vocabulary, with a section passing axe", async () => {
    const { container } = render(<Catalogue />);
    expect(screen.getByRole("heading", { level: 1, name: "Design system" })).toBeDefined();
    for (const id of CATALOGUE_SECTIONS) {
      expect(container.querySelector(`[data-catalogue-section="${id}"]`), id).not.toBeNull();
    }
    const hit = FORBIDDEN_TOKENS.exec(container.textContent ?? "");
    expect(hit?.[0], `found "${hit?.[0]}" on the catalogue page`).toBeUndefined();
    // axe over the whole catalogue is page sized and slow in jsdom on CI runners, so it checks
    // one section here; every component has its own axe test in packages/ui, and
    // e2e/design.spec.ts runs AxeBuilder over /design section by section.
    const states = container.querySelector<HTMLElement>('[data-catalogue-section="states"]');
    expect(states).not.toBeNull();
    expect(await runAxe(states as HTMLElement)).toHaveNoViolations();
  });

  it("sorts and pages the data table through its callbacks", async () => {
    const user = userEvent.setup();
    render(<Catalogue />);
    const table = screen.getByRole("table", { name: "Example items with sorting and paging" });
    const nameHeader = within(table).getByRole("columnheader", { name: /Name/ });
    expect(nameHeader.getAttribute("aria-sort")).toBe("ascending");
    await user.click(within(nameHeader).getByRole("button"));
    expect(nameHeader.getAttribute("aria-sort")).toBe("descending");
    const firstCell = within(table).getAllByRole("row")[1]?.querySelector("td");
    expect(firstCell?.textContent).toBe("Example item two");
    const dueHeader = within(table).getByRole("columnheader", { name: /Due/ });
    await user.click(within(dueHeader).getByRole("button"));
    expect(dueHeader.getAttribute("aria-sort")).toBe("ascending");
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("Page 2 of 3")).toBeDefined();
    await user.click(screen.getByRole("button", { name: "Previous page" }));
    expect(screen.getByText("Page 1 of 3")).toBeDefined();
  });

  it("opens the dialogs, records a reason and fires toasts", async () => {
    const user = userEvent.setup();
    render(<Catalogue />);
    await user.click(screen.getByRole("button", { name: "Open dialog" }));
    expect(screen.getByRole("dialog", { name: "Example dialog" })).toBeDefined();
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Open confirm dialog" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Open reason dialog" }));
    const reject = screen.getByRole("button", { name: "Reject" });
    expect(reject.hasAttribute("disabled")).toBe(true);
    await user.type(screen.getByRole("textbox", { name: /Reason/ }), "Example reason text");
    expect(reject.hasAttribute("disabled")).toBe(false);
    await user.click(reject);
    for (const name of ["Plain toast", "Success toast", "Error toast", "Info toast"]) {
      await user.click(screen.getByRole("button", { name }));
    }
    await user.click(screen.getByRole("button", { name: "Open sheet" }));
    expect(screen.getByRole("dialog", { name: "Example sheet" })).toBeDefined();
  });

  it("selects a day on the calendar", async () => {
    const user = userEvent.setup();
    render(<Catalogue />);
    const grid = screen.getByRole("grid", { name: "January 2000" });
    const cell = within(grid).getByRole("gridcell", { name: /Monday, 10 January 2000/ });
    await user.click(cell);
    expect(screen.getByText("Selected: 2000-01-10")).toBeDefined();
  });
});
