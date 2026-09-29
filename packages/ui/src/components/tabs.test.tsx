import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs";

describe("Tabs", () => {
  it("switches panels with the arrow keys and exposes the tab roles", async () => {
    const { container } = render(
      <Tabs defaultValue="one">
        <TabsList aria-label="Example sections">
          <TabsTrigger value="one">One</TabsTrigger>
          <TabsTrigger value="two">Two</TabsTrigger>
        </TabsList>
        <TabsContent value="one">Panel one</TabsContent>
        <TabsContent value="two">Panel two</TabsContent>
      </Tabs>,
    );
    expect(screen.getByRole("tablist", { name: "Example sections" })).toBeDefined();
    const one = screen.getByRole("tab", { name: "One" });
    expect(one.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tabpanel").textContent).toBe("Panel one");
    await userEvent.tab();
    expect(document.activeElement).toBe(one);
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Two" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tabpanel").textContent).toBe("Panel two");
    expect(container.querySelector('[data-slot="tabs"]')?.getAttribute("data-orientation")).toBe(
      "horizontal",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("moves focus from the active trigger into the panel, which shows the focus ring", async () => {
    render(
      <Tabs defaultValue="one">
        <TabsList aria-label="Example sections">
          <TabsTrigger value="one">One</TabsTrigger>
          <TabsTrigger value="two">Two</TabsTrigger>
        </TabsList>
        <TabsContent value="one">Panel one</TabsContent>
        <TabsContent value="two">Panel two</TabsContent>
      </Tabs>,
    );
    await userEvent.tab();
    expect(document.activeElement).toBe(screen.getByRole("tab", { name: "One" }));
    await userEvent.tab();
    const panel = screen.getByRole("tabpanel");
    expect(document.activeElement).toBe(panel);
    expect(panel.getAttribute("tabindex")).toBe("0");
    const classes = panel.className.split(/\s+/);
    expect(classes).toContain("focus-visible:ring-2");
    expect(classes).toContain("focus-visible:ring-focus");
    expect(classes).not.toContain("outline-none");
  });

  it("supports a vertical orientation", () => {
    render(
      <Tabs defaultValue="a" orientation="vertical">
        <TabsList>
          <TabsTrigger value="a">A</TabsTrigger>
        </TabsList>
        <TabsContent value="a">A panel</TabsContent>
      </Tabs>,
    );
    expect(screen.getByRole("tablist").getAttribute("aria-orientation")).toBe("vertical");
  });
});
