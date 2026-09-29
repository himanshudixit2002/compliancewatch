import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { businessFromDto } from "@/entities/business/mappers";
import type { ActionState } from "@/shared/lib/action-state";
import { BUSINESS_DTO, ENTITY_ID, REGISTRATION_ID } from "@/test/business-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import { attributesView, resolveNode, type AttributesInput } from "../model/business-pages";
import { AttributesView } from "./attributes-view";

const BUSINESS = businessFromDto(BUSINESS_DTO);
const NOW = new Date("2026-09-29T06:00:00Z");
const FIELDS = {
  businessId: "business_id",
  nodeId: "node_id",
  key: "key",
  asOfFy: "as_of_fy",
  value: "value",
};

function view(overrides: Partial<AttributesInput> = {}) {
  return attributesView({
    business: BUSINESS,
    resolved: resolveNode(BUSINESS, REGISTRATION_ID) as NonNullable<ReturnType<typeof resolveNode>>,
    ontology: ontologyFixture(),
    fy: "2000-01",
    canEdit: true,
    editHref: (key) => `/b/x/attributes?edit=${key}`,
    now: NOW,
    ...overrides,
  });
}

function renderView(model = view()) {
  return render(
    <AttributesView
      title="Attributes"
      view={model}
      header={{ crumbs: [], tabs: [] }}
      pageHref="/b/x/attributes"
      nodeHref={(id) => `/b/x/attributes?node=${id}`}
      closeHref="/b/x/attributes?node=r"
      saveAction={vi.fn(async (): Promise<ActionState> => ({ status: "idle" }))}
      fields={FIELDS}
    />,
  );
}

describe("AttributesView", () => {
  it("shows the node's own and inherited values, the pickers and what is not answered", async () => {
    const { container } = renderView();
    expect(screen.getByRole("heading", { level: 1, name: "Attributes" })).toBeDefined();
    const nodes = screen.getByRole("navigation", { name: "Business, registration or location" });
    expect(within(nodes).getByRole("link", { current: "page" }).textContent).toContain(
      "Example registration",
    );
    expect(within(nodes).getAllByRole("link")[0]?.getAttribute("href")).toBe(
      `/b/x/attributes?node=${ENTITY_ID}`,
    );
    const year = screen.getByRole("combobox", { name: "Financial year" }) as HTMLSelectElement;
    expect(year.value).toBe("2000-01");
    expect(year.closest("form")?.getAttribute("method")).toBe("get");
    const own = screen.getByRole("table", {
      name: "Values stored on 29ABCDE1234F1Z5 (Example registration) for 2000-01",
    });
    expect(within(own).getByText("Example second kind")).toBeDefined();
    expect(within(own).getByText("Does not apply")).toBeDefined();
    expect(
      within(own).getByRole("link", { name: "Change Example kind" }).getAttribute("href"),
    ).toBe("/b/x/attributes?edit=example_kind");
    const inherited = screen.getByRole("table", {
      name: "Values 29ABCDE1234F1Z5 (Example registration) inherits for 2000-01",
    });
    expect(within(inherited).getAllByText("Example business (PAN ABCDE1234F)")).toHaveLength(3);
    expect(screen.getByRole("link", { name: "Answer Example since" })).toBeDefined();
    expect(screen.queryByRole("heading", { name: /^Change / })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("opens the change form with the stored answer and the hidden fields", async () => {
    const { container } = renderView(view({ edit: "example_kind" }));
    const form = screen.getByRole("heading", {
      level: 2,
      name: "Change Example kind on 29ABCDE1234F1Z5 (Example registration)",
    });
    expect(form).toBeDefined();
    expect(
      screen.getByRole("radio", { name: "Example second kind" }).getAttribute("aria-checked"),
    ).toBe("true");
    expect(container.querySelector<HTMLInputElement>("input[name='node_id']")?.value).toBe(
      REGISTRATION_ID,
    );
    expect(container.querySelector<HTMLInputElement>("input[name='as_of_fy']")?.value).toBe("");
    expect(screen.getByRole("link", { name: "Close without changing" }).getAttribute("href")).toBe(
      "/b/x/attributes?node=r",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("names the year of a per-year answer being changed", () => {
    const entity = resolveNode(BUSINESS, undefined) as NonNullable<ReturnType<typeof resolveNode>>;
    renderView(view({ resolved: entity, edit: "example_band" }));
    expect(screen.getByText("The answer is for the financial year 2000-01.")).toBeDefined();
  });

  it("says when nothing is stored or missing, and offers no change to a reader", () => {
    const entity = resolveNode(BUSINESS, undefined) as NonNullable<ReturnType<typeof resolveNode>>;
    const model = view({ resolved: entity, canEdit: false });
    renderView({ ...model, own: [] });
    expect(screen.getByText("No value is stored on this node for this year.")).toBeDefined();
    expect(
      screen.getByText("Every attribute asked at this level has an answer for this year."),
    ).toBeDefined();
    expect(screen.queryByRole("link", { name: /^Change/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Inherited" })).toBeNull();
  });

  it("lists what is not answered without a link for a reader", () => {
    renderView(view({ canEdit: false }));
    expect(screen.getByText("Example since")).toBeDefined();
    expect(screen.queryByRole("link", { name: "Answer Example since" })).toBeNull();
  });
});
