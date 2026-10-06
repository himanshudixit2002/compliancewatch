import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { crawlRunFromDto, sourceFromDto, storedDocumentFromDto } from "@/entities/pipeline/mappers";
import type { ApiError } from "@/server/result";
import type { WriteAction } from "@/shared/ui/write-outcome";
import {
  DOCUMENT_ID,
  documentDto,
  runDto,
  sourceDto,
  uploadSourceDto,
} from "@/test/pipeline-fixture";
import { documentsView, settingsDefaults, sourceFacts } from "../model/source";
import type { SourcePage } from "../queries";
import { SourceView } from "./source-view";
import type { FetchResult, SettingsResult } from "./source-shared";

const CRUMBS = [
  { id: "admin.sources", href: "/admin/sources", label: "Sources" },
  { id: "admin.source", href: "/admin/sources/example_notices", label: "Example notices" },
];

const FLAG = {
  name: "pipeline.crawl",
  variable: "CW_PIPELINE_CRAWL_ENABLED",
  defaultOn: false,
  owner: "regulatory-intelligence",
};

function page(overrides: Partial<SourcePage> = {}, upload = false): SourcePage {
  const source = sourceFromDto(upload ? uploadSourceDto() : sourceDto());
  const pathname = `/admin/sources/${source.key}`;
  return {
    facts: sourceFacts(source),
    settings: settingsDefaults(source),
    documents: documentsView(pathname, null, {
      items: [storedDocumentFromDto(documentDto())],
      nextCursor: "n",
    }),
    documentsError: null,
    runs: upload ? [] : [crawlRunFromDto(runDto())],
    runsError: null,
    everyRunHref: `/admin/pipeline?view=runs&source=${source.key}`,
    access: { allowed: true },
    upload: { href: `/api-bff/pipeline/sources/${source.key}/uploads`, maxBytes: 25_000_000 },
    crawlFlag: FLAG,
    ...overrides,
  };
}

const edit = vi.fn<WriteAction<SettingsResult>>();
const fetchNow = vi.fn<WriteAction<FetchResult>>();

describe("SourceView", () => {
  it("shows a listing source's facts, its documents and runs, and an admin's fetch and settings", async () => {
    const { container } = render(
      <SourceView
        title="Example notices"
        crumbs={CRUMBS}
        page={page()}
        editAction={edit}
        fetchAction={fetchNow}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Example notices" })).toBeDefined();
    const facts = container.querySelector("[data-slot='source-facts']");
    expect(facts?.textContent).toContain("example_notices");
    expect(facts?.textContent).toContain("Every 2 h");
    expect(container.querySelector("[data-slot='fetch-panel']")).not.toBeNull();
    expect(container.querySelector("[data-slot='settings-panel']")).not.toBeNull();
    expect(container.querySelector("[data-slot='upload-panel']")).toBeNull();
    const documents = screen.getByRole("table", {
      name: "Documents of this source, the newest publication first (1 on this page)",
    });
    expect(
      within(documents).getByRole("link", { name: "Example notice 1" }).getAttribute("href"),
    ).toBe(`/admin/pipeline/documents/${DOCUMENT_ID}`);
    const file = within(documents).getByRole("link", { name: "Open the stored file (new tab)" });
    expect(file.getAttribute("href")).toBe(`/api-bff/pipeline/documents/${DOCUMENT_ID}/raw`);
    expect(file.getAttribute("target")).toBe("_blank");
    expect(screen.getByRole("link", { name: "Next documents" }).getAttribute("href")).toBe(
      "/admin/sources/example_notices?cursor=n",
    );
    expect(
      screen.getByRole("table", { name: "This source's latest crawl runs (1 shown)" }),
    ).toBeDefined();
    expect(
      screen.getByRole("link", { name: "Every run of this source" }).getAttribute("href"),
    ).toBe("/admin/pipeline?view=runs&source=example_notices");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("offers an upload-only source's upload form, and no fetch", async () => {
    const { container } = render(
      <SourceView
        title="Example statutes"
        crumbs={CRUMBS}
        page={page(
          {
            documents: documentsView("/admin/sources/example_statutes", null, {
              items: [],
              nextCursor: null,
            }),
          },
          true,
        )}
        editAction={edit}
        fetchAction={fetchNow}
      />,
    );
    expect(container.querySelector("[data-slot='upload-only']")).not.toBeNull();
    expect(container.querySelector("[data-slot='upload-panel']")).not.toBeNull();
    expect(container.querySelector("[data-slot='fetch-panel']")).toBeNull();
    expect(
      screen.getByRole("heading", { name: "No document stored from this source" }),
    ).toBeDefined();
    expect(
      screen.getByText(
        "Documents of an upload-only source arrive by upload; none has been uploaded yet.",
      ),
    ).toBeDefined();
    expect(screen.getByRole("heading", { name: "No crawl has run for this source" })).toBeDefined();
    expect(screen.queryByRole("link", { name: "Every run of this source" })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("reads only for an analyst, says why, and shows the documents' and runs' failures", () => {
    const failure: ApiError = {
      kind: "server",
      status: 500,
      requestId: "req-9",
      message: "Example failure",
    };
    const { container } = render(
      <SourceView
        title="Example notices"
        crumbs={CRUMBS}
        page={page({
          access: { allowed: false, title: "Only an admin changes a source" },
          documents: null,
          documentsError: failure,
          runs: null,
          runsError: { ...failure, requestId: "req-10" },
        })}
        editAction={null}
        fetchAction={null}
      />,
    );
    expect(container.querySelector("[data-slot='source-read-only']")?.textContent).toContain(
      "Only an admin changes a source",
    );
    expect(container.querySelector("[data-slot='fetch-panel']")).toBeNull();
    expect(container.querySelector("[data-slot='settings-panel']")).toBeNull();
    expect(screen.getByText("req-9")).toBeDefined();
    expect(screen.getByText("req-10")).toBeDefined();
  });

  it("says a later page of documents is past the end, with the way back", () => {
    render(
      <SourceView
        title="Example notices"
        crumbs={CRUMBS}
        page={page({
          documents: documentsView("/admin/sources/example_notices", "c", {
            items: [],
            nextCursor: null,
          }),
          access: {
            allowed: false,
            title: "The write token is not configured",
            detail: "Example detail",
          },
        })}
        editAction={null}
        fetchAction={null}
      />,
    );
    expect(screen.getByRole("heading", { name: "No more documents" })).toBeDefined();
    expect(screen.getByRole("link", { name: "First page" }).getAttribute("href")).toBe(
      "/admin/sources/example_notices",
    );
    expect(screen.getByText("Example detail")).toBeDefined();
  });
});
