import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import {
  crawlRunFromDto,
  outboxEventFromDto,
  pipelineDocumentFromDto,
} from "@/entities/pipeline/mappers";
import type { WriteAction } from "@/shared/ui/write-outcome";
import {
  DOCUMENT_ID,
  EVENT_ID,
  classificationDto,
  outboxEventDto,
  pipelineDocumentDto,
  runDto,
} from "@/test/pipeline-fixture";
import {
  documentRow,
  eventRow,
  pagedRows,
  readPipelineQuery,
  type PipelineRead,
} from "../model/operations";
import type { PipelinePage } from "../queries";
import { OutboxTable } from "./outbox-table";
import type { WriteResult } from "./pipeline-shared";
import { PipelineView } from "./pipeline-view";

const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.pipeline", href: "/admin/pipeline", label: "Pipeline" },
];

function page(read: PipelineRead, overrides: Partial<PipelinePage> = {}): PipelinePage {
  const current = read.current;
  const list: PipelinePage["list"] =
    current.view === "runs"
      ? {
          view: "runs",
          list: pagedRows(
            current,
            {
              items: [
                crawlRunFromDto(runDto()),
                crawlRunFromDto(
                  runDto({ run_id: "00000000-0000-4000-8000-0000000000a9", trigger: "backfill" }),
                ),
              ],
              nextCursor: "n",
            },
            (run) => run,
          ),
        }
      : current.view === "documents"
        ? {
            view: "documents",
            list: pagedRows(
              current,
              {
                items: [
                  pipelineDocumentFromDto(
                    pipelineDocumentDto({
                      classification: classificationDto({
                        classifier: "retry",
                        decided_by: "00000000-0000-4000-8000-0000000000e9",
                      }),
                    }),
                  ),
                ],
                nextCursor: null,
              },
              (document) => documentRow(document, null),
            ),
          }
        : {
            view: "outbox",
            list: pagedRows(
              current,
              { items: [outboxEventFromDto(outboxEventDto())], nextCursor: null },
              eventRow,
            ),
          };
  return {
    read,
    list,
    listError: null,
    sourceKeys: ["example_notices", "example_statutes"],
    access: { allowed: true },
    ...overrides,
  };
}

describe("PipelineView", () => {
  it("shows the runs with the view chips, the filters and a backfill marked", async () => {
    const { container } = render(
      <PipelineView
        title="Pipeline"
        crumbs={CRUMBS}
        pageHref="/admin/pipeline"
        page={page(readPipelineQuery({}))}
        requeueAction={null}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Pipeline" })).toBeDefined();
    const chips = screen.getByRole("navigation", { name: "Views of the pipeline" });
    expect(
      within(chips).getByRole("link", { name: "Crawl runs" }).getAttribute("aria-current"),
    ).toBe("true");
    expect(screen.getByRole("form", { name: "Filter the crawl runs" })).toBeDefined();
    expect(screen.getByLabelText("Source").querySelectorAll("option")).toHaveLength(3);
    expect(container.querySelectorAll("[data-run]")).toHaveLength(2);
    expect(
      container.querySelector("[data-trigger='backfill'] [data-slot='backfill-badge']"),
    ).not.toBeNull();
    expect(screen.getByRole("link", { name: "Next page" }).getAttribute("href")).toBe(
      "/admin/pipeline?cursor=n",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the documents with how the pipeline reads each one", async () => {
    const { container } = render(
      <PipelineView
        title="Pipeline"
        crumbs={CRUMBS}
        pageHref="/admin/pipeline"
        page={page(readPipelineQuery({ view: "documents" }))}
        requeueAction={null}
      />,
    );
    const row = container.querySelector(`[data-document='${DOCUMENT_ID}']`);
    expect(row?.textContent).toContain("Notification");
    expect(row?.querySelector("[data-slot='classification']")?.textContent).toContain(
      "A person's type, given on a retry",
    );
    expect(row?.textContent).toContain("00000000-0000-4000-8000-0000000000e9");
    expect(row?.querySelector("[data-slot='extraction']")?.textContent).toContain("Needs review");
    expect(screen.getByLabelText("Published from")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("marks a refused filter on its field, says why a list is empty, and shows a failed read", async () => {
    const read = readPipelineQuery({ view: "documents", from: "2000-13-01", source: "Bad Key" });
    const { container, rerender } = render(
      <PipelineView
        title="Pipeline"
        crumbs={CRUMBS}
        pageHref="/admin/pipeline"
        page={page(read, { list: null, sourceKeys: null })}
        requeueAction={null}
      />,
    );
    expect(screen.getByText("Give a date (YYYY-MM-DD), or leave it empty.")).toBeDefined();
    expect(screen.getByText(/A source key is lower-case letters/)).toBeDefined();
    expect(
      screen.getByText("The sources could not be read, so only the one named is offered."),
    ).toBeDefined();
    const empty = readPipelineQuery({ view: "outbox" });
    rerender(
      <PipelineView
        title="Pipeline"
        crumbs={CRUMBS}
        pageHref="/admin/pipeline"
        page={page(empty, {
          list: {
            view: "outbox",
            list: { rows: [], nextHref: null, firstHref: null, later: false },
          },
          access: { allowed: false, title: "Only an admin retries, requeues or resolves" },
        })}
        requeueAction={null}
      />,
    );
    expect(screen.getByRole("heading", { name: "No outbox row is dead" })).toBeDefined();
    expect(container.querySelector("[data-slot='pipeline-read-only']")).not.toBeNull();
    const filtered = readPipelineQuery({ status: "failed" });
    rerender(
      <PipelineView
        title="Pipeline"
        crumbs={CRUMBS}
        pageHref="/admin/pipeline"
        page={page(filtered, {
          list: { view: "runs", list: { rows: [], nextHref: null, firstHref: null, later: false } },
        })}
        requeueAction={null}
      />,
    );
    expect(screen.getByRole("heading", { name: "No crawl run matches the filter" })).toBeDefined();
    rerender(
      <PipelineView
        title="Pipeline"
        crumbs={CRUMBS}
        pageHref="/admin/pipeline"
        page={page(readPipelineQuery({ view: "documents", cursor: "c" }), {
          list: {
            view: "documents",
            list: {
              rows: [],
              nextHref: null,
              firstHref: "/admin/pipeline?view=documents",
              later: true,
            },
          },
        })}
        requeueAction={null}
      />,
    );
    expect(screen.getByRole("heading", { name: "No more rows" })).toBeDefined();
    rerender(
      <PipelineView
        title="Pipeline"
        crumbs={CRUMBS}
        pageHref="/admin/pipeline"
        page={page(readPipelineQuery({}), {
          list: null,
          listError: {
            kind: "server",
            status: 500,
            requestId: "req-7",
            message: "Example failure",
          },
        })}
        requeueAction={null}
      />,
    );
    expect(screen.getByText("req-7")).toBeDefined();
    for (const [view, title] of [
      ["runs", "No crawl has run"],
      ["documents", "No document is stored"],
    ] as const) {
      rerender(
        <PipelineView
          title="Pipeline"
          crumbs={CRUMBS}
          pageHref="/admin/pipeline"
          page={page(readPipelineQuery({ view }), {
            list: {
              view,
              list: { rows: [], nextHref: null, firstHref: null, later: false },
            } as PipelinePage["list"],
          })}
          requeueAction={null}
        />,
      );
      expect(screen.getByRole("heading", { name: title })).toBeDefined();
    }
    rerender(
      <PipelineView
        title="Pipeline"
        crumbs={CRUMBS}
        pageHref="/admin/pipeline"
        page={page(readPipelineQuery({ view: "documents", status: "triage" }), {
          list: {
            view: "documents",
            list: { rows: [], nextHref: null, firstHref: null, later: false },
          },
        })}
        requeueAction={null}
      />,
    );
    expect(screen.getByRole("heading", { name: "No document matches the filter" })).toBeDefined();
    rerender(
      <PipelineView
        title="Pipeline"
        crumbs={CRUMBS}
        pageHref="/admin/pipeline"
        page={page(readPipelineQuery({ view: "outbox", topic: "document.parsed" }), {
          list: {
            view: "outbox",
            list: { rows: [], nextHref: null, firstHref: null, later: false },
          },
        })}
        requeueAction={null}
      />,
    );
    expect(screen.getByRole("heading", { name: "No dead row of this topic" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe("OutboxTable", () => {
  it("lists the dead rows with what each is about, and requeues one with a reason", async () => {
    const action = vi.fn<WriteAction<WriteResult>>(async () => ({
      status: "ok",
      value: { message: "Back to pending: example." },
      message: "Back to pending: example.",
    }));
    const { container } = render(
      <OutboxTable rows={[eventRow(outboxEventFromDto(outboxEventDto()))]} action={action} />,
    );
    const row = container.querySelector(`[data-event='${EVENT_ID}']`);
    expect(row?.textContent).toContain("document.parsed");
    expect(row?.textContent).toContain("Failed sends: 8");
    expect(row?.textContent).toContain("Example broker error");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Requeue/ }));
    const dialog = await screen.findByRole("dialog", { name: "Requeue this document.parsed row?" });
    await user.type(within(dialog).getByRole("textbox"), "Example cause is fixed now");
    await user.click(within(dialog).getByRole("button", { name: "Requeue" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("Back to pending: example."),
    );
    const sent = action.mock.calls[0]?.[1];
    expect(sent?.get("event_id")).toBe(EVENT_ID);
    expect(sent?.get("reason")).toBe("Example cause is fixed now");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("offers no requeue to someone who may only read", () => {
    render(
      <OutboxTable
        rows={[
          eventRow(
            outboxEventFromDto(outboxEventDto({ summary: {}, last_error: "", dead_at: null })),
          ),
        ]}
        action={null}
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Requeue" })).toBeNull();
  });
});
