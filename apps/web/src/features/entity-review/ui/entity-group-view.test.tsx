import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { reviewItemFromDto } from "@/entities/rulebook/mappers";
import { reviewItemDto, reviewItemDtos } from "@/test/rulebook-fixture";
import { groupView } from "../model/group";
import type { DecideAction } from "./decision-panel";
import { EntityGroupView } from "./entity-group-view";

const PATH = "/admin/rulebook/entities";
const crumbs = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.rulebook.entities", href: PATH, label: "Entity review" },
];

describe("EntityGroupView", () => {
  const view = groupView("form", "EXAMPLE-1", [reviewItemFromDto(reviewItemDto())]);

  it("offers the decision when access allows it", async () => {
    const { container } = render(
      <EntityGroupView
        title="Entity group"
        crumbs={crumbs}
        queueHref={PATH}
        read={{ kind: "ok", entityType: "form", name: "EXAMPLE-1" }}
        view={view}
        access={{ allowed: true }}
        decide={vi.fn<DecideAction>()}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Decide the group" })).toBeDefined();
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("lists the mentions and names what holds the decision back", async () => {
    const { container } = render(
      <EntityGroupView
        title="Entity group"
        crumbs={crumbs}
        queueHref={PATH}
        read={{ kind: "ok", entityType: "form", name: "EXAMPLE-1" }}
        view={view}
        access={{ allowed: false, title: "Example flag is off", detail: "Example detail." }}
        decide={null}
      />,
    );
    expect(screen.getByText("Example flag is off")).toBeDefined();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Decide the group" })).toBeNull();
    expect(screen.getByRole("link", { name: "Show in the document" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("asks for a group when none is named, and says why an address is refused", async () => {
    const { container, rerender } = render(
      <EntityGroupView
        title="Entity group"
        crumbs={crumbs}
        queueHref={PATH}
        read={{ kind: "none" }}
        view={null}
        access={null}
        decide={null}
      />,
    );
    expect(screen.getByRole("heading", { name: "No group is named" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
    rerender(
      <EntityGroupView
        title="Entity group"
        crumbs={crumbs}
        queueHref={PATH}
        read={{ kind: "invalid", message: "Example refusal." }}
        view={null}
        access={null}
        decide={null}
      />,
    );
    expect(screen.getByText("Example refusal.")).toBeDefined();
  });

  it("says a list of the rulebook's 200 is the first 200 of a group that may hold more", () => {
    const capped = groupView("form", "EXAMPLE-1", reviewItemDtos(200).map(reviewItemFromDto));
    const { container, rerender } = render(
      <EntityGroupView
        title="Entity group"
        crumbs={crumbs}
        queueHref={PATH}
        read={{ kind: "ok", entityType: "form", name: "EXAMPLE-1" }}
        view={capped}
        access={{ allowed: false, title: "Example flag is off" }}
        decide={null}
      />,
    );
    const facts = container.querySelector("[data-slot='group-facts']");
    expect(facts?.textContent).toContain("200 or more (the first 200 listed)");
    expect(
      screen.getByText("The first 200 open mentions of EXAMPLE-1; the group may hold more."),
    ).toBeDefined();
    expect(container.querySelectorAll("tr[data-review-id]")).toHaveLength(200);
    rerender(
      <EntityGroupView
        title="Entity group"
        crumbs={crumbs}
        queueHref={PATH}
        read={{ kind: "ok", entityType: "form", name: "EXAMPLE-1" }}
        view={groupView("form", "EXAMPLE-1", reviewItemDtos(199).map(reviewItemFromDto))}
        access={{ allowed: false, title: "Example flag is off" }}
        decide={null}
      />,
    );
    expect(container.querySelector("[data-slot='group-facts']")?.textContent).not.toContain(
      "or more",
    );
    expect(screen.getByText("199 open mentions of EXAMPLE-1.")).toBeDefined();
  });

  it("says every mention is decided when access is refused and none is left", () => {
    render(
      <EntityGroupView
        title="Entity group"
        crumbs={crumbs}
        queueHref={PATH}
        read={{ kind: "ok", entityType: "form", name: "EXAMPLE-1" }}
        view={groupView("form", "EXAMPLE-1", [])}
        access={{ allowed: false, title: "Example refused" }}
        decide={null}
        error={{ message: "Example outage", requestId: "" }}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Every mention of this group is decided" }),
    ).toBeDefined();
    expect(screen.getByText("Example outage")).toBeDefined();
  });
});
