import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import {
  profileNodeFromDto,
  reviewTaskFromDto,
  snapshotFromDto,
} from "@/entities/business/mappers";
import {
  ENTITY_ID,
  REGISTRATION_DTO,
  REGISTRATION_ID,
  REVIEW_TASK_DTO,
  SNAPSHOT_DTO,
  TENANT_ID,
} from "@/test/business-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import { readLookup } from "../model/lookup";
import { nodeReviewView } from "../model/node-review";
import { ReviewTasksView } from "./review-tasks-view";

const PATH = "/admin/profiles/review-tasks";
const crumbs = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.profiles.review-tasks", href: PATH, label: "Profile review tasks" },
];
const NOW = new Date("2000-06-15T00:00:00Z");

describe("ReviewTasksView", () => {
  it("asks for a tenant and a node before a lookup", async () => {
    const { container } = render(
      <ReviewTasksView
        title="Profile review tasks"
        crumbs={crumbs}
        pageHref={PATH}
        lookup={readLookup({}, NOW)}
        view={null}
        notFound={false}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Profile review tasks" })).toBeDefined();
    expect((screen.getByLabelText(/^Financial year/) as HTMLInputElement).value).toBe("2000-01");
    expect(screen.getByText(/Give a tenant's id and the id of one of its nodes/)).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the node, its open tasks and its snapshot", async () => {
    const view = nodeReviewView({
      pathname: PATH,
      tenantId: TENANT_ID,
      fy: "2000-01",
      node: profileNodeFromDto(REGISTRATION_DTO),
      tasks: [reviewTaskFromDto(REVIEW_TASK_DTO)],
      snapshot: snapshotFromDto(SNAPSHOT_DTO),
      ontology: ontologyFixture(),
    });
    const { container } = render(
      <ReviewTasksView
        title="Profile review tasks"
        crumbs={crumbs}
        pageHref={PATH}
        lookup={readLookup({ tenant: TENANT_ID, node: REGISTRATION_ID, fy: "2000-01" }, NOW)}
        view={view}
        notFound={false}
      />,
    );
    expect(screen.getByRole("link", { name: ENTITY_ID }).getAttribute("href")).toBe(
      `${PATH}?tenant=${TENANT_ID}&node=${ENTITY_ID}&fy=2000-01`,
    );
    expect(container.querySelector(`[data-task='${REVIEW_TASK_DTO.id}']`)?.textContent).toContain(
      "Example definition of example_flag.",
    );
    expect(
      screen.getByRole("heading", { name: "What the engine evaluates for 2000-01" }),
    ).toBeDefined();
    expect(container.querySelector("[data-attribute='example_band']")?.textContent).toContain(
      "Example medium band",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says when the tenant holds no such node, marks bad fields and shows a failed read", async () => {
    const { container, rerender } = render(
      <ReviewTasksView
        title="Profile review tasks"
        crumbs={crumbs}
        pageHref={PATH}
        lookup={readLookup({ tenant: TENANT_ID, node: REGISTRATION_ID }, NOW)}
        view={null}
        notFound
      />,
    );
    expect(
      screen.getByRole("heading", { name: "No node with this id in this tenant" }),
    ).toBeDefined();
    rerender(
      <ReviewTasksView
        title="Profile review tasks"
        crumbs={crumbs}
        pageHref={PATH}
        lookup={readLookup({ tenant: "x", node: REGISTRATION_ID }, NOW)}
        view={null}
        notFound={false}
        error={{ message: "Example outage", status: 503, requestId: "req-example-7" }}
      />,
    );
    expect(screen.getByText("This is not a tenant id (a UUID).")).toBeDefined();
    expect(screen.getByText("Example outage")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
