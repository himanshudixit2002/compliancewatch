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
