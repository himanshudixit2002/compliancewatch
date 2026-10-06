import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { dryRunReportFromDto } from "@/entities/applicability/mappers";
import { dryRunOutDto } from "@/test/engine-admin-fixture";
import { dryRunView } from "../model/report";
import { DryRunReport } from "./dry-run-report";

describe("DryRunReport", () => {
  it("says nothing was in scope, with no attribute and no sample", async () => {
    const report = dryRunView(
      dryRunReportFromDto(
        dryRunOutDto({
          businesses_total: 0,
          evaluated: 0,
          counts: { applies: 0, not_applicable: 0, unsure: 0 },
          needs_review: 0,
          by_attribute: [],
          samples: [],
        }),
      ),
      null,
    );
    const { container } = render(<DryRunReport report={report} />);
    expect(screen.getByRole("heading", { level: 2, name: "No business in scope" })).toBeDefined();
    expect(screen.getByText("No attribute decided a result.")).toBeDefined();
    expect(screen.getByText("No sample was kept.")).toBeDefined();
    expect(
      screen.getByText("0 in scope, 0 decided, 0 no longer in the profile service"),
    ).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
