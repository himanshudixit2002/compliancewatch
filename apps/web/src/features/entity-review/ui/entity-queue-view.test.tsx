import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { mentionGroupFromDto } from "@/entities/rulebook/mappers";
import { mentionGroupDto } from "@/test/rulebook-fixture";
import { queueView, readQueue } from "../model/queue";
import { EntityQueueView } from "./entity-queue-view";

const PATH = "/admin/rulebook/entities";
const crumbs = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.rulebook.entities", href: PATH, label: "Entity review" },
];

describe("EntityQueueView", () => {
  it("lists the groups with their open mentions and a link to each", async () => {
    const read = readQueue({});
    const view = queueView(PATH, { entityType: null, after: null }, [
      mentionGroupFromDto(mentionGroupDto()),
    ]);
    const { container } = render(
      <EntityQueueView
        title="Entity review"
        crumbs={crumbs}
        pageHref={PATH}
        read={read}
        view={view}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Entity review" })).toBeDefined();
    expect(screen.getByRole("link", { name: "EXAMPLE-1" }).getAttribute("href")).toBe(
      "/admin/rulebook/entities/group?type=form&name=EXAMPLE-1",
    );
    expect(screen.getByText("1 groups on this page, holding 2 open mentions.")).toBeDefined();
    expect(screen.getByText("No entity has this name")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says why the queue is empty, for a type too", () => {
    const read = readQueue({ type: "hsn_code" });
    render(
      <EntityQueueView
        title="Entity review"
        crumbs={crumbs}
        pageHref={PATH}
        read={read}
        view={queueView(PATH, { entityType: "hsn_code", after: null }, [])}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "No HSN code mention waits for review" }),
    ).toBeDefined();
  });

  it("marks a type it does not know on the field and shows a failed read", async () => {
    const { container } = render(
      <EntityQueueView
        title="Entity review"
        crumbs={crumbs}
        pageHref={PATH}
        read={readQueue({ type: "example" })}
        view={null}
        error={{ message: "Example outage", status: 503, requestId: "req-example-1" }}
      />,
    );
    expect(screen.getByText("Choose an entity type from the list.")).toBeDefined();
    expect(screen.getByText("Example outage")).toBeDefined();
    expect(screen.getByText("req-example-1")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
