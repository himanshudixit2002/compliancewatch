import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import {
  ApplicabilityBadge,
  applicabilityLabel,
  applicabilityTone,
  levelLabel,
} from "./applicability";

describe("ApplicabilityBadge", () => {
  it("says each result in words, with the review a person owes", async () => {
    const { container } = render(
      <p>
        <ApplicabilityBadge result="applies" />
        <ApplicabilityBadge result="not_applicable" />
        <ApplicabilityBadge result="unsure" needsReview />
      </p>,
    );
    expect(screen.getByText("Applies").getAttribute("data-result")).toBe("applies");
    expect(screen.getByText("Does not apply").getAttribute("data-tone")).toBe("neutral");
    expect(screen.getByText("Not sure, needs review").getAttribute("data-tone")).toBe("warning");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("gives the label and tone to the views that build their own", () => {
    expect(applicabilityLabel("applies")).toBe("Applies");
    expect(applicabilityLabel("applies", true)).toBe("Applies, needs review");
    expect(applicabilityTone("applies")).toBe("success");
    expect(applicabilityTone("unsure")).toBe("warning");
  });

  it("names the level a rule is decided at", () => {
    expect(levelLabel("entity")).toBe("Legal entities (PAN)");
    expect(levelLabel("registration")).toBe("Registrations (GSTIN)");
    expect(levelLabel("location")).toBe("Places of business");
  });
});
