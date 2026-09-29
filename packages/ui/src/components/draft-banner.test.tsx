import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { DRAFT_BANNER_TEXT, DraftBanner } from "./draft-banner";

describe("DraftBanner", () => {
  it("shows the fixed draft wording and the document version", async () => {
    const { container } = render(<DraftBanner version="0.1-draft" />);
    const banner = screen.getByRole("status");
    expect(banner.dataset.slot).toBe("draft-banner");
    expect(banner.dataset.tone).toBe("warning");
    expect(banner.textContent).toContain(DRAFT_BANNER_TEXT);
    expect(banner.textContent).toContain("Version 0.1-draft");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
