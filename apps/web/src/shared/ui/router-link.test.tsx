import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RouterLink } from "./router-link";

describe("RouterLink", () => {
  it("renders an anchor with the href, class and aria-current it is given", () => {
    render(
      <RouterLink href="/sitemap" className="x" aria-current="page">
        All screens
      </RouterLink>,
    );
    const link = screen.getByRole("link", { name: "All screens" });
    expect(link.getAttribute("href")).toBe("/sitemap");
    expect(link.className).toBe("x");
    expect(link.getAttribute("aria-current")).toBe("page");
  });
});
