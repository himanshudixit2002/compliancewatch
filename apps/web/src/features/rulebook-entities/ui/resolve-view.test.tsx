import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { resolutionFromDto } from "@/entities/rulebook/mappers";
import { EXAMPLE_ENTITY_ID, EXAMPLE_OTHER_ENTITY_ID, entityDto } from "@/test/rulebook-fixture";
import { readResolve } from "../model/resolve-form";
import { resolutionView } from "../model/resolution";
import { ResolveView, type ResolveViewProps } from "./resolve-view";

const PAGE = "/admin/rulebook/entities/canonical";
const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.rulebook.canonical", href: PAGE, label: "Canonical entities" },
];

function renderView(props: Partial<ResolveViewProps>) {
  return render(
    <ResolveView
      title="Canonical entities"
      crumbs={CRUMBS}
      pageHref={PAGE}
      read={{ kind: "empty" }}
      resolution={null}
      {...props}
    />,
  );
}

describe("ResolveView", () => {
  it("asks for a type and a name with a GET form before anything is resolved", async () => {
    const { container } = renderView({});
    expect(screen.getByRole("heading", { level: 1, name: "Canonical entities" })).toBeDefined();
    const form = screen.getByRole("form", { name: "Resolve a name" });
    expect(form.getAttribute("method")).toBe("get");
    expect(form.getAttribute("action")).toBe(PAGE);
    expect(within(form).getByRole("option", { name: "HSN code" })).toBeDefined();
    expect(screen.getByRole("heading", { name: "Resolve a name to an entity" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows a resolved name with its status, its normalised form and the entity to open", async () => {
    const read = readResolve({ type: "form", name: "Example Form" });
    const { container } = renderView({
      read,
      resolution: resolutionView(
        resolutionFromDto({
          status: "resolved",
          entity_type: "form",
          name: "Example Form",
          normalised: "example form",
          entity: entityDto(),
          candidates: [],
        }),
      ),
    });
    const result = container.querySelector("[data-slot='resolution']") as HTMLElement;
    expect(result.getAttribute("data-status")).toBe("resolved");
    expect(within(result).getByText("Resolved")).toBeDefined();
    expect(within(result).getByText("example form", { selector: "code" })).toBeDefined();
    expect(
      within(result).getByRole("link", { name: "Form: example form" }).getAttribute("href"),
    ).toBe(`${PAGE}/${EXAMPLE_ENTITY_ID}`);
    expect(within(result).getByText("Aliases: example form 1, form e")).toBeDefined();
    expect((screen.getByLabelText(/^Name/) as HTMLInputElement).value).toBe("Example Form");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("offers each candidate of an ambiguous alias, and says when nothing is left of a name", () => {
    const { container, rerender } = renderView({
      read: readResolve({ type: "form", name: "Example" }),
      resolution: resolutionView(
        resolutionFromDto({
          status: "ambiguous",
          entity_type: "form",
          name: "Example",
          normalised: "example",
          entity: null,
          candidates: [
            entityDto({ aliases: [] }),
            entityDto({ entity_id: EXAMPLE_OTHER_ENTITY_ID, canonical_name: "example two" }),
          ],
        }),
      ),
    });
    expect(screen.getByRole("heading", { name: "The entities sharing this alias" })).toBeDefined();
    expect(container.querySelectorAll("[data-slot='entity-choices'] li")).toHaveLength(2);
    expect(screen.getByText("No alias")).toBeDefined();
    rerender(
      <ResolveView
        title="Canonical entities"
        crumbs={CRUMBS}
        pageHref={PAGE}
        read={readResolve({ type: "state", name: "--" })}
        resolution={resolutionView(
          resolutionFromDto({
            status: "empty",
            entity_type: "state",
            name: "--",
            normalised: "",
            entity: null,
            candidates: [],
          }),
        )}
      />,
    );
    expect(screen.getByText("(nothing)")).toBeDefined();
    expect(screen.queryByRole("link", { name: /State:/ })).toBeNull();
  });

  it("marks refused fields and shows a failed read", () => {
    renderView({ read: readResolve({ type: "example", name: "" }) });
    expect(screen.getByText("Choose the entity type.")).toBeDefined();
    expect(screen.getByText("Enter the name to resolve.")).toBeDefined();
    renderView({
      read: readResolve({ type: "form", name: "Example" }),
      error: { message: "Example failure", requestId: "req-example-9" },
    });
    expect(screen.getByRole("alert").textContent).toContain("req-example-9");
  });
});
