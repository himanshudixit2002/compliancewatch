import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { relationFromDto } from "@/entities/rulebook/mappers";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import { relationDto } from "@/test/rulebook-fixture";
import {
  EXAMPLE_OTHER_VERSION_ID,
  EXAMPLE_VERSION_ID,
  ruleVersionDto,
} from "@/test/rule-version-fixture";
import { readGraph } from "../model/graph-form";
import {
  entityNode,
  graphEdge,
  layoutGraph,
  versionNode,
  type GraphView as GraphViewModel,
} from "../model/graph";
import { GraphView, type GraphViewProps } from "./graph-view";

const PAGE = "/admin/rulebook/relations/graph";
const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  {
    id: "admin.rulebook.relations",
    href: "/admin/rulebook/relations",
    label: "Relation candidates",
  },
  { id: "admin.rulebook.relations.graph", href: PAGE, label: "Relations graph" },
];

function graph(overrides: Partial<GraphViewModel> = {}): GraphViewModel {
  const start = ruleVersionFromDto(ruleVersionDto());
  const startNode = versionNode(EXAMPLE_VERSION_ID, 0, start, true);
  const other = versionNode(
    EXAMPLE_OTHER_VERSION_ID,
    1,
    ruleVersionFromDto(
      ruleVersionDto({
        rule_version_id: EXAMPLE_OTHER_VERSION_ID,
        version: 2,
        status: "published",
      }),
    ),
  );
  const entityRelation = relationFromDto(relationDto({ to_entity_id: null }));
  const entity = entityNode(entityRelation, 1);
  const extension = relationFromDto(
    relationDto({
      relation_id: "r2",
      relation: "extends_deadline",
      to_kind: "rule_version",
      to_ref: EXAMPLE_OTHER_VERSION_ID,
      to_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
      to_entity_id: null,
      period_label: "2000-03",
      new_due_on: "2000-04-21",
    }),
  );
  const nodes = [startNode, other, entity];
  const edges = [
    graphEdge(extension, startNode.key, other.key),
    graphEdge(entityRelation, startNode.key, entity.key),
  ];
  return {
    start,
    depth: 1,
    publishedOnly: false,
    nodes,
    edges,
    layout: layoutGraph(nodes, edges),
    truncated: false,
    ...overrides,
  };
}

function renderView(props: Partial<GraphViewProps>) {
  return render(
    <GraphView
      title="Relations graph"
      crumbs={CRUMBS}
      pageHref={PAGE}
      read={{ kind: "empty" }}
      graph={null}
      {...props}
    />,
  );
}

describe("GraphView", () => {
  it("asks for a version with a GET form before anything is drawn", async () => {
    const { container } = renderView({});
    const form = screen.getByRole("form", { name: "Draw the relations around a version" });
    expect(form.getAttribute("method")).toBe("get");
    expect(
      screen.getByRole("heading", { name: "Choose a rule version to start from" }),
    ).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("draws the relations as a picture hidden from assistive technology, and lists them in a table", async () => {
    const { container } = renderView({
      read: readGraph({ rule_version_id: EXAMPLE_VERSION_ID }),
      graph: graph(),
    });
    expect(
      screen.getByRole("heading", { name: "Around example_rule v1: Example rule title" }),
    ).toBeDefined();
    expect(
      screen.getByText(/3 versions and entities, 2 relations, up to 1 relations out/),
    ).toBeDefined();
    const svg = container.querySelector("[data-slot='graph-picture'] svg") as SVGSVGElement;
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.querySelectorAll("[data-node]")).toHaveLength(3);
    expect(svg.querySelectorAll("[data-edge]")).toHaveLength(2);
    expect(svg.querySelector("a")).toBeNull();
    const table = container.querySelector("[data-slot='graph-table']") as HTMLElement;
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(
      within(rows[0] as HTMLElement).getByRole("link", { name: "example_rule v2" }),
    ).toBeDefined();
    expect(
      within(rows[0] as HTMLElement).getByText("Period 2000-03, due 21 Apr 2000"),
    ).toBeDefined();
    expect(within(rows[0] as HTMLElement).getByText("(start)")).toBeDefined();
    expect(within(rows[1] as HTMLElement).getByText("Form: example form")).toBeDefined();
    expect((screen.getByLabelText(/^Rule version id/) as HTMLInputElement).value).toBe(
      EXAMPLE_VERSION_ID,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says when the version has no relation, and when the graph was cut short", () => {
    const lone = graph();
    renderView({
      read: readGraph({ rule_version_id: EXAMPLE_VERSION_ID, scope: "published" }),
      graph: {
        ...lone,
        nodes: [lone.nodes[0]!],
        edges: [],
        layout: layoutGraph([lone.nodes[0]!], []),
        publishedOnly: true,
        truncated: true,
      },
    });
    expect(
      screen.getByRole("heading", { name: "No relation from or to this version" }),
    ).toBeDefined();
    expect(
      screen.getByText("No published version states a relation from or to this version."),
    ).toBeDefined();
    expect(screen.getByText("The graph is cut short")).toBeDefined();
  });

  it("answers a malformed or unknown version on the field and shows a failed read", () => {
    renderView({ read: readGraph({ rule_version_id: "example" }) });
    expect(screen.getByText("This is not a rule version id (a UUID).")).toBeDefined();
    renderView({ read: readGraph({ rule_version_id: EXAMPLE_VERSION_ID }), unknownVersion: true });
    expect(screen.getByText("The rulebook holds no rule version with this id.")).toBeDefined();
    renderView({
      read: readGraph({ rule_version_id: EXAMPLE_VERSION_ID }),
      error: { message: "Example failure", requestId: "req-example-7" },
    });
    expect(
      screen.getAllByRole("alert").some((alert) => alert.textContent?.includes("req-example-7")),
    ).toBe(true);
  });
});
