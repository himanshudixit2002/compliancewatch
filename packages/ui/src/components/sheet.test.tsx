import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Button } from "./button";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "./sheet";

describe("Sheet", () => {
  it("opens from the side, is labelled and closes with its close controls", async () => {
    render(
      <Sheet>
        <SheetTrigger asChild>
          <Button>Menu</Button>
        </SheetTrigger>
        <SheetContent side="left">
          <SheetHeader>
            <SheetTitle>Navigation</SheetTitle>
            <SheetDescription>Example links</SheetDescription>
          </SheetHeader>
          <SheetFooter>
            <SheetClose asChild>
              <Button variant="secondary">Done</Button>
            </SheetClose>
          </SheetFooter>
        </SheetContent>
      </Sheet>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Menu" }));
    const sheet = screen.getByRole("dialog", { name: "Navigation" });
    expect(sheet.dataset.side).toBe("left");
    expect(sheet.className).toContain("left-0");
    expect(await runAxe(sheet)).toHaveNoViolations();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("defaults to the right side and offers the corner close button", async () => {
    render(
      <Sheet defaultOpen>
        <SheetContent>
          <SheetTitle>Panel</SheetTitle>
          <SheetDescription>Example</SheetDescription>
        </SheetContent>
      </Sheet>,
    );
    const sheet = screen.getByRole("dialog", { name: "Panel" });
    expect(sheet.dataset.side).toBe("right");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
