import { render, screen } from "@testing-library/react";
import { DRAFT_BANNER_TEXT } from "@compliancewatch/ui";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { LegalDocument } from "./legal-document";

describe("LegalDocument", () => {
  it("renders the draft banner with the version above the document", async () => {
    const { container } = render(
      <LegalDocument version="0.1-draft" html="<h1>Privacy notice</h1><p>Example text.</p>" />,
    );
    expect(screen.getByText(DRAFT_BANNER_TEXT)).toBeDefined();
    expect(screen.getByText(/Version 0.1-draft/)).toBeDefined();
    expect(screen.getByRole("heading", { level: 1, name: "Privacy notice" })).toBeDefined();
    expect(screen.getByText("Example text.")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
