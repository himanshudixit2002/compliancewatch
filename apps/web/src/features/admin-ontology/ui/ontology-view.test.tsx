import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { ontologyFixture } from "@/test/ontology-fixture";
import { ontologyBrowserView, usageNote } from "../model/browser";
import { OntologyView } from "./ontology-view";

const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.ontology", href: "/admin/ontology", label: "Ontology" },
];

describe("OntologyView", () => {
  it("shows the facts, the waiting usage counts and one table per level", async () => {
    const view = ontologyBrowserView(ontologyFixture());
    const { container } = render(
      <OntologyView title="Ontology" crumbs={CRUMBS} view={view} usage={usageNote()} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Ontology" })).toBeDefined();
    const facts = container.querySelector("dl[aria-label='About this ontology']") as HTMLElement;
    expect(facts.textContent).toContain("0.0.1, language en");
    expect(facts.textContent).toContain("Needs an analyst's review");
    expect(facts.textContent).toContain(String(view.total));

    const usage = container.querySelector("[data-slot='usage-awaits']");
    expect(usage?.textContent).toContain(
      "GET /v1/profile/admin/attribute-usage (services track (WP30))",
    );
    expect(screen.getByText("Attribute usage: not shown yet")).toBeDefined();

    expect(screen.getAllByRole("heading", { level: 2 }).map((node) => node.textContent)).toEqual([
      "Legal entity (PAN)",
      "Registration (GSTIN)",
      "Location",
    ]);
    const entity = container.querySelector("[data-level='entity']") as HTMLElement;
    expect(
      within(entity).getByText("4 attributes, in the order onboarding asks for them"),
    ).toBeDefined();
    const band = entity.querySelector("[data-attribute='example_band']") as HTMLElement;
    expect(band.textContent).toContain("Per financial year");
    expect(band.textContent).toContain("Example medium band");
    expect(band.textContent).toContain("Example: Example medium band");
    expect(band.textContent).toContain("eq, neq, in, not_in, gt, gte, lt, lte");
    const count = entity.querySelector("[data-attribute='example_count']") as HTMLElement;
    expect(count.textContent).toContain("0 to 1000");
    const derived = entity.querySelector("[data-attribute='example_derived']") as HTMLElement;
    expect(derived.textContent).toContain("Not asked: the service works it out.");
    const note = container.querySelector("[data-attribute='example_note']") as HTMLElement;
    expect(note.textContent).toContain("Any value of its type");
    expect(note.textContent).toContain("None");
    expect(screen.queryByText("Attributes this app cannot show")).toBeNull();
    expect(await runAxe(entity)).toHaveNoViolations();
  });

  it("says which attributes it cannot show, marks reviewed wording, and explains an empty ontology", async () => {
    const ontology = ontologyFixture();
    const view = ontologyBrowserView({
      ...ontology,
      attributes: [],
      unsupported: ["example_unknown"],
      wordingReviewed: true,
    });
    const { container } = render(
      <OntologyView title="Ontology" crumbs={CRUMBS} view={view} usage={usageNote()} />,
    );
    expect(screen.getByText("Attributes this app cannot show")).toBeDefined();
    expect(screen.getByText(/left out: example_unknown\./)).toBeDefined();
    expect(screen.getByText("Reviewed by an analyst")).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: "No attributes" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
