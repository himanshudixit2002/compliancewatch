import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { taskFromDto } from "@/entities/pipeline/mappers";
import type { WriteAction } from "@/shared/ui/write-outcome";
import { ACTOR_ID, TASK_ID, TRIAGE_TASK_ID, taskDto, triageTaskDto } from "@/test/pipeline-fixture";
import { tasksView, type TaskFilter } from "../model/tasks";
import type { WriteResult } from "./pipeline-shared";
import { TaskPanel } from "./task-panel";
import { TasksView } from "./tasks-view";

const CRUMBS = [
  { id: "admin.pipeline", href: "/admin/pipeline", label: "Pipeline" },
  { id: "admin.pipeline.tasks", href: "/admin/pipeline/tasks", label: "Pipeline tasks" },
];
const OPEN: TaskFilter = { status: "open", kind: null, cursor: null };

function done(message: string): ActionStateLike {
  return { status: "ok", value: { message }, message };
}

type ActionStateLike = Awaited<ReturnType<WriteAction<WriteResult>>>;

describe("TasksView", () => {
  it("lists the open tasks with their documents, chips and the panels for an admin", async () => {
    const view = tasksView(
      OPEN,
      { items: [taskFromDto(taskDto()), taskFromDto(triageTaskDto())], nextCursor: "n" },
      ACTOR_ID,
    );
    const resolve = vi.fn<WriteAction<WriteResult>>();
    const dismiss = vi.fn<WriteAction<WriteResult>>();
    const { container } = render(
      <TasksView
        title="Pipeline tasks"
        crumbs={CRUMBS}
        view={view}
        access={{ allowed: true }}
        actionsFor={() => ({ resolve, dismiss })}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Pipeline tasks" })).toBeDefined();
    const status = screen.getByRole("navigation", { name: "Show tasks by status" });
    expect(within(status).getByRole("link", { name: "Open" }).getAttribute("aria-current")).toBe(
      "true",
    );
    const manual = container.querySelector(`[data-task='${TASK_ID}']`) as HTMLElement;
    expect(manual.textContent).toContain("Manual parse");
    expect(manual.textContent).toContain("pdf@1: no text layer");
    expect(
      within(manual).getByRole("link", { name: "Open the stored file (new tab)" }),
    ).toBeDefined();
    expect(
      manual.querySelector("[data-slot='task-panel'][data-kind='manual_parse']"),
    ).not.toBeNull();
    const triage = container.querySelector(`[data-task='${TRIAGE_TASK_ID}']`) as HTMLElement;
    expect(triage.querySelector("[data-slot='task-panel'][data-kind='triage']")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Next tasks" }).getAttribute("href")).toBe(
      "/admin/pipeline/tasks?cursor=n",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("reads closed tasks without panels, and says why a list is empty", async () => {
    const closed = tasksView(
      { status: "resolved", kind: null, cursor: null },
      {
        items: [
          taskFromDto(
            triageTaskDto({
              status: "resolved",
              resolved_by: ACTOR_ID,
              resolved_at: "2000-01-03T00:00:00Z",
              note: "Example note on the decision",
              resolution: { relevance: "relevant", doc_type: "circular", route: "extract" },
            }),
          ),
          taskFromDto(taskDto({ status: "dismissed", note: "" })),
        ],
        nextCursor: null,
      },
      null,
    );
    const { container, rerender } = render(
      <TasksView
        title="Pipeline tasks"
        crumbs={CRUMBS}
        view={closed}
        access={{ allowed: false, title: "Only an admin retries, requeues or resolves" }}
        actionsFor={null}
      />,
    );
    expect(container.querySelector("[data-slot='task-panel']")).toBeNull();
    expect(container.querySelector("[data-slot='tasks-read-only']")).not.toBeNull();
    expect(container.textContent).toContain("Example note on the decision");
    expect(container.textContent).toContain("The pipeline, when a parse succeeded");
    expect(await runAxe(container)).toHaveNoViolations();
    const cases: [TaskFilter, string][] = [
      [OPEN, "No task is open"],
      [{ status: "dismissed", kind: null, cursor: null }, "No task is dismissed"],
      [{ status: null, kind: "triage", cursor: null }, "No triage task"],
      [{ status: null, kind: null, cursor: null }, "The pipeline holds no task"],
      [
        { status: "resolved", kind: "manual_parse", cursor: null },
        "No manual parse task is resolved",
      ],
      [{ status: "open", kind: null, cursor: "c" }, "No more tasks"],
    ];
    for (const [filter, title] of cases) {
      rerender(
        <TasksView
          title="Pipeline tasks"
          crumbs={CRUMBS}
          view={tasksView(filter, { items: [], nextCursor: null }, null)}
          access={{ allowed: true }}
          actionsFor={null}
        />,
      );
      expect(screen.getByRole("heading", { name: title })).toBeDefined();
    }
  });
});

describe("TaskPanel", () => {
  it("reads a transcript as the pipeline will, and resolves the manual parse with it", async () => {
    const resolve = vi.fn<WriteAction<WriteResult>>(async () =>
      done("Resolved: its ingest started (workflow w)."),
    );
    const dismiss = vi.fn<WriteAction<WriteResult>>();
    const { container } = render(
      <TaskPanel
        kind="manual_parse"
        resolve={resolve}
        dismiss={dismiss}
        documentTitle="Example notice 1"
      />,
    );
    const user = userEvent.setup();
    const submit = screen.getByRole("button", {
      name: "Resolve with this transcript",
    }) as HTMLButtonElement;
    await user.type(screen.getByLabelText(/^The document, typed in/), "#");
    expect(screen.getByText("Block 1: the heading has no text.")).toBeDefined();
    await user.type(
      screen.getByLabelText(/^The document, typed in/),
      " Example heading{enter}{enter}1. Example text.",
    );
    expect(container.querySelector("[data-slot='transcript-counts']")?.textContent).toBe(
      "Headings: 1; paragraphs: 1; tables: 0; clauses in all: 2",
    );
    await user.type(screen.getByLabelText(/^The document's title/), "Example title");
    expect(submit.disabled).toBe(true);
    await user.type(screen.getByLabelText(/^Why/), "Example reason of enough length");
    await user.click(submit);
    const dialog = screen.getByRole("dialog", { name: "Resolve the task on Example notice 1?" });
    expect(dialog.textContent).toContain("clauses in it: 2");
    await user.click(within(dialog).getByRole("button", { name: "Resolve with this transcript" }));
    await waitFor(() =>
      expect(container.querySelector("[data-slot='write-done']")?.textContent).toBe(
        "Resolved: its ingest started (workflow w).",
      ),
    );
    const sent = resolve.mock.calls[0]?.[1];
    expect(sent?.get("title")).toBe("Example title");
    expect(sent?.get("transcript")).toBe("# Example heading\n\n1. Example text.");
    expect(dismiss).not.toHaveBeenCalled();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("resolves a triage with a type, says what follows, and shows the pipeline's refusal", async () => {
    const resolve = vi.fn<WriteAction<WriteResult>>(async () => ({
      status: "error",
      problem: {
        type: "urn:compliancewatch:problem:pipeline-task-closed",
        title: "The task is closed already",
        correlationId: "req-8",
      },
      fieldErrors: { doc_type: ["Example type message"] },
    }));
    render(
      <TaskPanel
        kind="triage"
        resolve={resolve}
        dismiss={vi.fn()}
        documentTitle="Example notice 1"
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "A regulator's document" }));
    await user.selectOptions(screen.getByLabelText(/^Its type/), "circular");
    await user.type(screen.getByLabelText(/^Why/), "Example reason of enough length");
    await user.click(screen.getByRole("button", { name: "Resolve the triage" }));
    expect(screen.getByRole("dialog").textContent).toContain("extracts its rule candidate");
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Resolve the triage" }),
    );
    await waitFor(() => expect(screen.getByText("The task is closed already")).toBeDefined());
    expect(screen.getByText("Example type message")).toBeDefined();
    expect(resolve.mock.calls[0]?.[1].get("doc_type")).toBe("circular");
    await user.click(screen.getByRole("radio", { name: "A regulator's document" }));
    await user.selectOptions(screen.getByLabelText(/^Its type/), "statute");
    await user.click(screen.getByRole("button", { name: "Resolve the triage" }));
    expect(screen.getByRole("dialog").textContent).toContain("keeps it for reference");
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("radio", { name: "Not a regulatory document" }));
    await user.click(screen.getByRole("button", { name: "Resolve the triage" }));
    expect(screen.getByRole("dialog").textContent).toContain("set aside");
  });

  it("dismisses a task with a reason", async () => {
    const dismiss = vi.fn<WriteAction<WriteResult>>(async () => done("Dismissed: example."));
    const resolve = vi.fn<WriteAction<WriteResult>>();
    const { container } = render(
      <TaskPanel
        kind="triage"
        resolve={resolve}
        dismiss={dismiss}
        documentTitle="Example notice 1"
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Dismiss the task" }));
    const dialog = screen.getByRole("dialog", { name: "Dismiss the task on Example notice 1?" });
    expect(dialog.textContent).toContain("held for triage");
    await user.type(within(dialog).getByRole("textbox"), "Example duplicate of another notice");
    await user.click(within(dialog).getByRole("button", { name: "Dismiss the task" }));
    await waitFor(() =>
      expect(container.querySelector("[data-slot='write-done']")?.textContent).toBe(
        "Dismissed: example.",
      ),
    );
    expect(dismiss.mock.calls[0]?.[1].get("reason")).toBe("Example duplicate of another notice");
    expect(resolve).not.toHaveBeenCalled();
    render(
      <TaskPanel
        kind="manual_parse"
        resolve={resolve}
        dismiss={dismiss}
        documentTitle="Example two"
      />,
    );
    await user.click(screen.getAllByRole("button", { name: "Dismiss the task" })[1] as HTMLElement);
    expect(
      screen.getByRole("dialog", { name: "Dismiss the task on Example two?" }).textContent,
    ).toContain("unread by any parser");
  });
});
