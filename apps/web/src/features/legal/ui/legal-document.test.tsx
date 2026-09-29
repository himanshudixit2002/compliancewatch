import { render, screen } from "@testing-library/react";
import { DRAFT_BANNER_TEXT } from "@compliancewatch/ui";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { LegalDocument } from "./legal-document";

const HTML = "<h1>Example notice</h1><p>Example clause text.</p>";

describe("LegalDocument", () => {
  it("renders the draft banner with the version above a draft", async () => {
    const { container } = render(
      <LegalDocument title="Example notice" version="0.1-draft" isDraft html={HTML} />,
    );
    expect(screen.getByText(DRAFT_BANNER_TEXT)).toBeDefined();
    expect(screen.getByText(/Version 0.1-draft/)).toBeDefined();
    expect(screen.getByRole("heading", { level: 1, name: "Example notice" })).toBeDefined();
    expect(screen.getByText("Example clause text.")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows a plain version line and no banner once the document is reviewed", () => {
    const { container } = render(
      <LegalDocument title="Example notice" version="1.0" isDraft={false} html={HTML} />,
    );
    expect(screen.queryByText(DRAFT_BANNER_TEXT)).toBeNull();
    expect(container.querySelector("[data-slot='legal-version']")?.textContent).toBe("Version 1.0");
  });

  it("carries a line for paper only, naming the document and its version", () => {
    const { container } = render(
      <LegalDocument title="Example notice" version="0.1-draft" isDraft html={HTML} />,
    );
    const printed = container.querySelector("[data-slot='legal-printed']");
    expect(printed?.textContent).toBe(
      "Printed from ComplianceWatch: Example notice, version 0.1-draft.",
    );
    expect(printed?.className).toContain("hidden");
    expect(printed?.className).toContain("print:block");
  });
});
