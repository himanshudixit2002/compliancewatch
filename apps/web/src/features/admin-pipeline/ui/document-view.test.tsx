import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { documentDetailFromDto } from "@/entities/pipeline/mappers";
import type { WriteAction } from "@/shared/ui/write-outcome";
import {
  ACTOR_ID,
  DOCUMENT_ID,
  classificationDto,
  documentDetailDto,
  retryDto,
} from "@/test/pipeline-fixture";
import { documentPageView } from "../model/document";
import { DocumentView } from "./document-view";
import type { WriteResult } from "./pipeline-shared";

const CRUMBS = [
  { id: "admin.pipeline", href: "/admin/pipeline", label: "Pipeline" },
  {
    id: "admin.pipeline.document",
    href: `/admin/pipeline/documents/${DOCUMENT_ID}`,
    label: "Example notice 1",
  },
];
const KEY = "00000000-0000-4000-8000-0000000000a1";

function view(overrides: Parameters<typeof documentDetailDto>[0] = {}) {
  return documentPageView(documentDetailFromDto(documentDetailDto(overrides)), ACTOR_ID);
}

describe("DocumentView", () => {
  it("shows the record, how the pipeline reads it and its retries, with the stored file", async () => {
    const { container } = render(
      <DocumentView
        title="Example notice 1"
        crumbs={CRUMBS}
        view={view({
          classification: classificationDto({
            classifier: "triage",
            decided_by: ACTOR_ID,
            task_id: "00000000-0000-4000-8000-0000000000b2",
          }),
          retries: [retryDto(), retryDto({ attempt: 2, doc_type: "circular" })],
        })}
        access={{ allowed: false, title: "Only an admin retries, requeues or resolves" }}
        retryAction={null}
        retryKey={KEY}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Example notice 1" })).toBeDefined();
    const facts = container.querySelector("[data-slot='document-facts']");
    expect(facts?.textContent).toContain(DOCUMENT_ID);
    expect(
      within(facts as HTMLElement)
        .getByRole("link", { name: "Open the stored file (new tab)" })
        .getAttribute("href"),
    ).toBe(`/api-bff/pipeline/documents/${DOCUMENT_ID}/raw`);
    const classification = container.querySelector("[data-slot='classification-facts']");
    expect(classification?.textContent).toContain("A person's triage");
    expect(classification?.textContent).toContain("you");
    expect(classification?.textContent).toContain("00000000-0000-4000-8000-0000000000b2");
    expect(screen.getByText("The opening names a notification")).toBeDefined();
    expect(container.querySelector("[data-slot='extraction-facts']")?.textContent).toContain(
      "Needs review",
    );
    const retries = screen.getByRole("table", {
      name: "Retries of the document, the latest first (2 in all)",
    });
    expect(within(retries).getAllByRole("row")[1]?.textContent).toContain("as a Circular");
    expect(container.querySelector("[data-slot='document-read-only']")?.textContent).toContain(
      "Only an admin retries, requeues or resolves",
    );
    expect(container.querySelector("[data-slot='retry-panel']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says a document is not classified, extracted or retried yet", () => {
    render(
      <DocumentView
        title="Example notice 1"
        crumbs={CRUMBS}
        view={view({
          classification: null,
          extraction: null,
          retries: [],
          parser_version: "",
          published_on: null,
          external_ref: "",
        })}
        access={{
          allowed: false,
          title: "The write token is not configured",
          detail: "Example detail",
        }}
        retryAction={null}
        retryKey={KEY}
      />,
    );
    expect(screen.getByText(/^Not classified yet/)).toBeDefined();
    expect(screen.getByText(/^None by the current prompt/)).toBeDefined();
    expect(screen.getByRole("heading", { name: "No retry yet" })).toBeDefined();
    expect(screen.getByText("Not parsed yet")).toBeDefined();
    expect(screen.getByText("Example detail")).toBeDefined();
  });

  it("lets an admin retry from a stage as a type, with the render's key, and send the same request again", async () => {
    const answers = [
      {
        status: "error" as const,
        problem: {
          type: "urn:compliancewatch:problem:pipeline-ingest-unavailable",
          title: "Temporal did not answer: send the same request again",
          correlationId: "req-example-5",
        },
      },
      {
        status: "ok" as const,
        value: { message: "Attempt 2 from Classify recorded." },
        message: "Attempt 2 from Classify recorded.",
      },
    ];
    const action = vi.fn<WriteAction<WriteResult>>(
      async () => answers.shift() ?? { status: "idle" },
    );
    const { container } = render(
      <DocumentView
        title="Example notice 1"
        crumbs={CRUMBS}
        view={view()}
        access={{ allowed: true }}
        retryAction={action}
        retryKey={KEY}
      />,
    );
    const user = userEvent.setup();
    const panel = container.querySelector("[data-slot='retry-panel']") as HTMLElement;
    await user.click(within(panel).getByRole("radio", { name: "Classify" }));
    await user.selectOptions(within(panel).getByLabelText(/^Read it as/), "press_release");
    await user.type(within(panel).getByLabelText(/^Why/), "Example reason of enough length");
    await user.click(within(panel).getByRole("button", { name: "Retry the document" }));
    const dialog = await screen.findByRole("dialog", { name: "Retry Example notice 1?" });
    expect(dialog.textContent).toContain("as a Press release");
    await user.click(within(dialog).getByRole("button", { name: "Retry the document" }));
    await waitFor(() =>
      expect(
        screen.getByText("Temporal did not answer: send the same request again"),
      ).toBeDefined(),
    );
    expect(await runAxe(container)).toHaveNoViolations();
    await user.click(screen.getByRole("button", { name: "Send the same request again" }));
    await waitFor(() =>
      expect(container.querySelector("[data-slot='write-done']")?.textContent).toBe(
        "Attempt 2 from Classify recorded.",
      ),
    );
    const [first, second] = action.mock.calls.map((call) => call[1]);
    expect(second).toBe(first);
    expect(first?.get("stage")).toBe("classify");
    expect(first?.get("doc_type")).toBe("press_release");
    expect(first?.get("idempotency_key")).toBe(KEY);
  });

  it("keeps the key of a retry Temporal did not start when the page renders again, until it is settled", async () => {
    const answers = [
      {
        status: "error" as const,
        problem: {
          type: "urn:compliancewatch:problem:pipeline-ingest-unavailable",
          title: "Temporal did not answer: send the same request again",
        },
      },
      {
        status: "ok" as const,
        value: { message: "Attempt 1 from Parse replayed." },
        message: "Attempt 1 from Parse replayed.",
      },
      {
        status: "ok" as const,
        value: { message: "Attempt 2 from Parse recorded." },
        message: "Attempt 2 from Parse recorded.",
      },
    ];
    const action = vi.fn<WriteAction<WriteResult>>(
      async () => answers.shift() ?? { status: "idle" },
    );
    const page = (retryKey: string) => (
      <DocumentView
        title="Example notice 1"
        crumbs={CRUMBS}
        view={view()}
        access={{ allowed: true }}
        retryAction={action}
        retryKey={retryKey}
      />
    );
    const { container, rerender } = render(page(KEY));
    const user = userEvent.setup();
    const panel = container.querySelector("[data-slot='retry-panel']") as HTMLElement;
    const retry = async () => {
      await user.click(within(panel).getByRole("button", { name: "Retry the document" }));
      await user.click(
        within(await screen.findByRole("dialog")).getByRole("button", {
          name: "Retry the document",
        }),
      );
    };
    await user.type(within(panel).getByLabelText(/^Why/), "Example reason of enough length");
    await retry();
    await waitFor(() =>
      expect(
        screen.getByText("Temporal did not answer: send the same request again"),
      ).toBeDefined(),
    );
    // The answer renders the page again, which mints a new key; the form's Retry keeps the first.
    rerender(page("00000000-0000-4000-8000-0000000000a2"));
    await retry();
    await waitFor(() =>
      expect(container.querySelector("[data-slot='write-done']")?.textContent).toBe(
        "Attempt 1 from Parse replayed.",
      ),
    );
    // Settled: the next retry is a new request, with the key of the render that followed.
    rerender(page("00000000-0000-4000-8000-0000000000a3"));
    await retry();
    await waitFor(() => expect(action).toHaveBeenCalledTimes(3));
    expect(action.mock.calls.map((call) => call[1].get("idempotency_key"))).toEqual([
      KEY,
      KEY,
      "00000000-0000-4000-8000-0000000000a3",
    ]);
  });

  it("warns that no rule is extracted from a type kept for reference", async () => {
    const action = vi.fn<WriteAction<WriteResult>>(async () => ({ status: "idle" }));
    const { container } = render(
      <DocumentView
        title="Example"
        crumbs={CRUMBS}
        view={view()}
        access={{ allowed: true }}
        retryAction={action}
        retryKey={KEY}
      />,
    );
    const panel = container.querySelector("[data-slot='retry-panel']") as HTMLElement;
    const user = userEvent.setup();
    await user.click(within(panel).getByRole("radio", { name: "Extract" }));
    await user.selectOptions(within(panel).getByLabelText(/^Read it as/), "statute");
    expect(within(panel).getByText(/No rule is extracted from this type/)).toBeDefined();
    await user.type(within(panel).getByLabelText(/^Why/), "Example reason of enough length");
    await user.click(within(panel).getByRole("button", { name: "Retry the document" }));
    expect((await screen.findByRole("dialog")).textContent).toContain("from Extract");
  });
});
