import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { businessFromDto, snapshotFromDto } from "@/entities/business/mappers";
import { BUSINESS_DTO, REGISTRATION_ID, SNAPSHOT_DTO } from "@/test/business-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import { resolveNode, snapshotView } from "../model/business-pages";
import { SnapshotView } from "./snapshot-view";

const BUSINESS = businessFromDto(BUSINESS_DTO);
const VIEW = snapshotView(
  BUSINESS,
  resolveNode(BUSINESS, REGISTRATION_ID) as NonNullable<ReturnType<typeof resolveNode>>,
  snapshotFromDto(SNAPSHOT_DTO),
  ontologyFixture(),
  "2000-01",
  new Date("2026-09-29T06:00:00Z"),
);

describe("SnapshotView", () => {
  it("lists each value with where it comes from, for the node and year", async () => {
    const { container } = render(
      <SnapshotView
        title="Snapshot"
        view={VIEW}
        header={{ crumbs: [], tabs: [] }}
        pageHref="/b/x/snapshot"
        nodeHref={(id) => `/b/x/snapshot?node=${id}`}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Snapshot" })).toBeDefined();
    expect(screen.getByText(/This is what the applicability engine evaluates/)).toBeDefined();
    expect(screen.getByText("29ABCDE1234F1Z5 (Example registration)")).toBeDefined();
    const table = screen.getByRole("table", { name: "Snapshot for 2000-01" });
    const kind = within(table).getByText("Example kind").closest("tr");
    expect(kind?.textContent).toContain("Stored on this node");
    expect(
      within(table).getAllByText("Inherited from Example business (PAN ABCDE1234F)"),
    ).toHaveLength(2);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says when the snapshot holds nothing", () => {
    render(
      <SnapshotView
        title="Snapshot"
        view={{ ...VIEW, rows: [] }}
        header={{ crumbs: [], tabs: [] }}
        pageHref="/b/x/snapshot"
        nodeHref={(id) => id}
      />,
    );
    expect(screen.getByText("The snapshot holds no value for this node and year.")).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
