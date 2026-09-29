import type { ReactNode } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { AppShell } from "./app-shell";

const items = [
  { href: "/", label: "Home", active: true },
  { href: "/calendar", label: "Calendar" },
];

describe("AppShell", () => {
  it("renders the skip link, primary navigation, user menu and main landmark", async () => {
    const { container } = render(
      <AppShell items={items} userMenu={<button type="button">Account</button>}>
        <h1>Page</h1>
      </AppShell>,
    );
    const skip = screen.getByRole("link", { name: "Skip to main content" });
    expect(skip.getAttribute("href")).toBe("#main");
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const active = within(nav).getByRole("link", { name: "Home" });
    expect(active.getAttribute("aria-current")).toBe("page");
    expect(
      within(nav).getByRole("link", { name: "Calendar" }).getAttribute("aria-current"),
    ).toBeNull();
    expect(screen.getByRole("link", { name: "ComplianceWatch" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("button", { name: "Account" })).toBeDefined();
    const main = screen.getByRole("main");
    expect(main.id).toBe("main");
    expect(main.getAttribute("tabindex")).toBe("-1");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("opens the navigation sheet on small screens", async () => {
    render(
      <AppShell items={items} productName="Example" homeHref="/home">
        <p>Body</p>
      </AppShell>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    const sheet = screen.getByRole("dialog", { name: "Navigation" });
    expect(within(sheet).getByRole("link", { name: "Calendar" }).getAttribute("href")).toBe(
      "/calendar",
    );
    expect(await runAxe(sheet)).toHaveNoViolations();
  });

  it("renders links through the component the app supplies", () => {
    function Link({
      href,
      children,
      className,
      ...rest
    }: {
      href: string;
      children: ReactNode;
      className?: string;
    }) {
      return (
        <a href={href} data-custom-link className={className} {...rest}>
          {children}
        </a>
      );
    }
    render(
      <AppShell items={items} Link={Link}>
        <p>Body</p>
      </AppShell>,
    );
    expect(
      screen.getByRole("link", { name: "ComplianceWatch" }).hasAttribute("data-custom-link"),
    ).toBe(true);
  });
});
