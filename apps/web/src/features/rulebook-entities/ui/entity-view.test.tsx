import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import {
  entityFromDto,
  mentionedClauseFromDto,
  relationFromDto,
} from "@/entities/rulebook/mappers";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import {
  EXAMPLE_ENTITY_ID,
  entityDto,
  mentionedClauseDto,
  relationDto,
} from "@/test/rulebook-fixture";
import { EXAMPLE_VERSION_ID, ruleVersionDto } from "@/test/rule-version-fixture";
import { mentionedClauseView, relationToEntity, type EntityPageView } from "../model/entity-page";
import { EntityView } from "./entity-view";

const PAGE = `/admin/rulebook/entities/canonical/${EXAMPLE_ENTITY_ID}`;
const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  {
    id: "admin.rulebook.canonical",
    href: "/admin/rulebook/entities/canonical",
    label: "Canonical entities",
  },
  { id: "admin.rulebook.canonical.entity", href: PAGE, label: "example form" },
];

function pageView(overrides: Partial<EntityPageView> = {}): EntityPageView {
  return {
    entity: entityFromDto(entityDto()),
    typeLabel: "Form",
    asOf: null,
    clauses: {
      ok: true,
      value: [
        mentionedClauseView(mentionedClauseFromDto(mentionedClauseDto({ out_of_force: true }))),
      ],
    },
    relations: {
      ok: true,
      value: [
        relationToEntity(
          relationFromDto(relationDto()),
          new Map([[EXAMPLE_VERSION_ID, ruleVersionFromDto(ruleVersionDto())]]),
        ),
      ],
    },
    ...overrides,
  };
}

describe("EntityView", () => {
  it("shows the entity with its aliases, the clauses that mention it marked, and the relations to it", async () => {
    const { container } = render(<EntityView view={pageView()} crumbs={CRUMBS} pageHref={PAGE} />);
    expect(screen.getByRole("heading", { level: 1, name: "example form" })).toBeDefined();
    const aliases = container.querySelector("[data-slot='aliases']") as HTMLElement;
    expect(within(aliases).getAllByRole("listitem")).toHaveLength(2);
    const clause = container.querySelector("[data-slot='mentioned-clauses'] li") as HTMLElement;
    expect(within(clause).getByText("Clause en.p1 of Example 1/2000")).toBeDefined();
    expect([...clause.querySelectorAll("mark")].map((mark) => mark.textContent)).toEqual([
      "example form",
      "example form 1",
    ]);
    expect(within(clause).getByText("Its rule is out of force on this date")).toBeDefined();
    expect(
      within(clause)
        .getByRole("link", { name: "Open clause en.p1 in its document" })
        .getAttribute("href"),
    ).toContain("start=21&end=33");
    const relations = container.querySelector("[data-slot='entity-relations']") as HTMLElement;
    expect(within(relations).getByRole("link", { name: "example_rule v1" })).toBeDefined();
    expect(within(relations).getByText("Refers to")).toBeDefined();
    const form = screen.getByRole("form", { name: "Show the clauses as of a date" });
    expect(form.getAttribute("method")).toBe("get");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says why nothing is listed, by date, and shows failed parts with their ids", () => {
    const { rerender } = render(
      <EntityView
        view={pageView({
          asOf: "2000-06-30",
          clauses: { ok: true, value: [] },
          relations: { ok: true, value: [] },
          entity: entityFromDto(entityDto({ aliases: [] })),
        })}
        crumbs={CRUMBS}
        pageHref={PAGE}
      />,
    );
    expect(
      screen.getByText("No document published by 30 Jun 2000 mentions this entity."),
    ).toBeDefined();
    expect(screen.getByText("No rule version states a relation to this entity.")).toBeDefined();
    expect(screen.getByText("No alias")).toBeDefined();
    rerender(
      <EntityView
        view={pageView({
          clauses: { ok: true, value: [] },
          relations: {
            ok: false,
            error: { message: "Example relations failure", requestId: "req-r" },
          },
        })}
        crumbs={CRUMBS}
        pageHref={PAGE}
        invalidAsOf="2000-99-99"
      />,
    );
    expect(
      screen.getByText("The rulebook holds no aligned mention of this entity yet."),
    ).toBeDefined();
    expect(screen.getByText("Example relations failure")).toBeDefined();
    expect(screen.getByText("Enter a date as YYYY-MM-DD.")).toBeDefined();
    rerender(
      <EntityView
        view={pageView({
          clauses: { ok: false, error: { message: "Example clauses failure", requestId: "req-c" } },
        })}
        crumbs={CRUMBS}
        pageHref={PAGE}
      />,
    );
    expect(screen.getByText("Example clauses failure")).toBeDefined();
  });
});
