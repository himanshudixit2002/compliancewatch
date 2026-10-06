import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { initialValues } from "../model/form";
import type { DryRunAction } from "./dry-run-form";
import { ImpactView } from "./impact-view";

describe("ImpactView", () => {
  it("says what a dry run stores and offers the form", async () => {
    const { container } = render(
      <ImpactView
        title="Impact explorer"
        crumbs={[{ id: "admin.impact", href: "/admin/impact", label: "Impact explorer" }]}
        action={vi.fn<DryRunAction>()}
        initial={initialValues(null)}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Impact explorer" })).toBeDefined();
    expect(screen.getByText(/stores no decision and tells nobody/)).toBeDefined();
    expect(screen.getByRole("form", { name: "Run a dry run" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
