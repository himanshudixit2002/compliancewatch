import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Button } from "./button";
import { PageHeader } from "./page-header";

describe("PageHeader", () => {
  it("renders the h1, description, breadcrumbs and actions", async () => {
    const { container } = render(
      <PageHeader
        title="Example page"
        description="What this page is for."
        breadcrumbs={<nav aria-label="Breadcrumb">crumbs</nav>}
        actions={<Button>Act</Button>}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Example page" })).toBeDefined();
    expect(screen.getByText("What this page is for.")).toBeDefined();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Act" })).toBeDefined();
    expect(container.querySelector("header")?.dataset.slot).toBe("page-header");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("renders only the title when nothing else is given", () => {
    render(<PageHeader title="Plain" />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Plain");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
