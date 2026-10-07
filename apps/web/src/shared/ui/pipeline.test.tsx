import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import {
  DocumentStatusChip,
  RunsTable,
  documentStatusLabel,
  documentStatusTone,
  documentTypeLabel,
  runStatusLabel,
  runStatusTone,
  runTriggerLabel,
  sourceHref,
  type PipelineRunLike,
} from "./pipeline";

const RUN: PipelineRunLike = {
  runId: "00000000-0000-4000-8000-0000000000a1",
  sourceKey: "example_notices",
  status: "completed",
  trigger: "schedule",
  workflowId: "pipeline-crawl-example_notices-946684800",
  startedAt: "2000-01-01T04:30:00Z",
  finishedAt: "2000-01-01T04:31:05Z",
  listed: 12,
  stored: 3,
  duplicates: 1,
  failed: 0,
  error: "",
};

describe("the pipeline's words", () => {
  it("say a document's status and type, and humanise a value the spec adds later", () => {
    expect(documentStatusLabel("triage")).toBe("Held for triage");
    expect(documentStatusTone("failed")).toBe("danger");
    expect(documentStatusLabel("example_new")).toBe("Example new");
    expect(documentStatusTone("example_new")).toBe("neutral");
    expect(documentTypeLabel("press_release")).toBe("Press release");
    expect(documentTypeLabel(null)).toBe("Not known");
    expect(documentTypeLabel("example_kind")).toBe("Example kind");
  });

  it("say a run's status and why it ran", () => {
    expect(runStatusLabel("failed")).toBe("Failed");
    expect(runStatusTone("running")).toBe("info");
    expect(runStatusLabel("example")).toBe("Example");
    expect(runStatusTone("example")).toBe("neutral");
    expect(runTriggerLabel("manual")).toBe("Fetched by an admin");
    expect(runTriggerLabel(null)).toBe("Not recorded");
    expect(runTriggerLabel("example_trigger")).toBe("Example trigger");
    expect(sourceHref("example_notices")).toBe("/admin/sources/example_notices");
  });

  it("shows a document's status as a chip", async () => {
    const { container } = render(<DocumentStatusChip status="extracted" />);
    expect(screen.getByText("Extracted")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe("RunsTable", () => {
  it("lists each run with its source, a backfill marked as one, its counts and its error", async () => {
    const { container } = render(
      <RunsTable
        caption="Example runs"
        showSource
        empty={{ title: "None", body: "None yet" }}
        runs={[
          RUN,
          {
            ...RUN,
            runId: "00000000-0000-4000-8000-0000000000a2",
            trigger: "backfill",
            status: "failed",
            error: "Example listing error",
            finishedAt: null,
            workflowId: null,
          },
        ]}
      />,
    );
    expect(screen.getByRole("table", { name: "Example runs" })).toBeDefined();
    expect(screen.getAllByRole("link", { name: "example_notices" })[0]?.getAttribute("href")).toBe(
      "/admin/sources/example_notices",
    );
    expect(container.querySelector("[data-slot='backfill-badge']")?.textContent).toBe("Backfill");
    expect(screen.getByText("Example listing error")).toBeDefined();
    expect(
      screen.getAllByText("12 listed; of the new ones 3 stored, 1 duplicates, 0 failed"),
    ).toHaveLength(2);
    expect(screen.getByText("Not finished")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("leaves the source out on a source's own page and says why a list is empty", () => {
    const { container, rerender } = render(
      <RunsTable
        caption="Example runs"
        showSource={false}
        empty={{ title: "None", body: "x" }}
        runs={[RUN]}
      />,
    );
    expect(screen.queryByRole("columnheader", { name: "Source" })).toBeNull();
    expect(container.querySelector("[data-run]")?.getAttribute("data-trigger")).toBe("schedule");
    rerender(
      <RunsTable
        caption="Example runs"
        showSource
        empty={{ title: "No runs yet", body: "Example reason" }}
        runs={[]}
      />,
    );
    expect(screen.getByRole("heading", { name: "No runs yet" })).toBeDefined();
  });
});
