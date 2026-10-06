import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { NotLegalAdvice } from "./not-legal-advice";

describe("NotLegalAdvice", () => {
  it("says the service is not advice and links to the terms", async () => {
    const { container } = render(<NotLegalAdvice />);
    const footer = screen.getByRole("complementary", { name: "Not legal advice" });
    expect(footer.textContent).toMatch(/not legal, tax or accounting advice/);
    expect(
      screen.getByRole("link", { name: "Terms of service, section 2" }).getAttribute("href"),
    ).toBe("/legal/terms-of-service");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
