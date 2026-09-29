import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ThemeToggle, applyTheme, readTheme } from "./theme-toggle";

describe("theme helpers", () => {
  it("read and apply the forced scheme on an element", () => {
    const root = document.createElement("div");
    expect(readTheme(root)).toBe("system");
    applyTheme(root, "dark");
    expect(readTheme(root)).toBe("dark");
    applyTheme(root, "light");
    expect(root.classList.contains("dark")).toBe(false);
    expect(readTheme(root)).toBe("light");
    applyTheme(root, "system");
    expect(root.className).toBe("");
  });
});

describe("ThemeToggle", () => {
  it("forces dark or light on the document and hands back to the system", async () => {
    document.documentElement.className = "dark";
    const user = userEvent.setup();
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Dark" }).getAttribute("aria-pressed")).toBe("true");
    await user.click(screen.getByRole("button", { name: "Light" }));
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    await user.click(screen.getByRole("button", { name: "System" }));
    expect(document.documentElement.className).toBe("");
    expect(screen.getByRole("button", { name: "System" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
  });
});
