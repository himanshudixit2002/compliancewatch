import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  RuleVersionStatusChip,
  SeedStatusChip,
  ruleVersionStatusLabel,
} from "./rule-version-status";

describe("RuleVersionStatusChip", () => {
  it("names each status in words with its tone", () => {
    const { rerender } = render(<RuleVersionStatusChip status="in_review" />);
    expect(screen.getByText("In review").getAttribute("data-tone")).toBe("info");
    rerender(<RuleVersionStatusChip status="published" />);
    expect(screen.getByText("Published").getAttribute("data-tone")).toBe("success");
    rerender(<RuleVersionStatusChip status="withdrawn" />);
    expect(screen.getByText("Withdrawn").getAttribute("data-tone")).toBe("danger");
    rerender(<RuleVersionStatusChip status="draft" />);
    expect(screen.getByText("Draft").getAttribute("data-status")).toBe("draft");
  });

  it("humanises a status the app does not know, in the neutral tone", () => {
    render(<RuleVersionStatusChip status="example_state" />);
    expect(screen.getByText("Example state").getAttribute("data-tone")).toBe("neutral");
    expect(ruleVersionStatusLabel("approved")).toBe("Approved");
    expect(ruleVersionStatusLabel("superseded")).toBe("Superseded");
  });
});

describe("SeedStatusChip", () => {
  it("says a version is not yet reviewed until an approval completes a round", () => {
    const { rerender } = render(<SeedStatusChip seedStatus="needs_review" />);
    expect(screen.getByText("Not yet reviewed").getAttribute("data-tone")).toBe("warning");
    rerender(<SeedStatusChip seedStatus="reviewed" />);
    expect(screen.getByText("Reviewed").getAttribute("data-tone")).toBe("success");
    rerender(<SeedStatusChip seedStatus="example_state" />);
    expect(screen.getByText("Example state").getAttribute("data-tone")).toBe("neutral");
  });
});
