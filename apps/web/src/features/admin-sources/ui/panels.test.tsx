import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WriteAction } from "@/shared/ui/write-outcome";
import { FetchPanel } from "./fetch-panel";
import { SettingsPanel } from "./settings-panel";
import { readUploadAnswer, type FetchResult, type SettingsResult } from "./source-shared";
import { UploadPanel } from "./upload-panel";

const DEFAULTS = {
  name: "Example notices",
  cadenceSeconds: 7200,
  enabled: true,
  paused: false,
  parameters: '{\n  "listing": "notices"\n}',
};

function entries(formData: FormData): Record<string, string> {
  return Object.fromEntries([...formData.entries()].map(([key, value]) => [key, String(value)]));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SettingsPanel", () => {
  it("sends the settings with the reason after a dialog, and shows what was saved", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<WriteAction<SettingsResult>>(async (_state, formData) => {
      sent.push(entries(formData));
      return {
        status: "ok",
        value: { message: "Saved: paused.", changed: ["paused"] },
        message: "Saved: paused.",
      };
    });
    const { container } = render(<SettingsPanel action={action} defaults={DEFAULTS} listable />);
    const user = userEvent.setup();
    const save = screen.getByRole("button", { name: "Save the settings" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    await user.click(screen.getByRole("checkbox", { name: /^Paused/ }));
    await user.type(screen.getByLabelText(/^Why/), "Example reason of enough length");
    await user.click(save);
    const dialog = await screen.findByRole("dialog", { name: "Save these settings?" });
    await user.click(within(dialog).getByRole("button", { name: "Save the settings" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Saved: paused."));
    expect(sent).toEqual([
      {
        name: "Example notices",
        cadence_seconds: "7200",
        enabled: "on",
        paused: "on",
        parameters: DEFAULTS.parameters,
        reason: "Example reason of enough length",
        rendered_name: "Example notices",
        rendered_cadence_seconds: "7200",
        rendered_enabled: "on",
        rendered_paused: "off",
        rendered_parameters: DEFAULTS.parameters,
      },
    ]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("starts again from the source when the page renders it otherwise, keeping the last answer", async () => {
    const action = vi.fn<WriteAction<SettingsResult>>(async () => ({
      status: "ok",
      value: { message: "Saved: cadence.", changed: ["cadenceSeconds"] },
      message: "Saved: cadence.",
    }));
    const { rerender } = render(<SettingsPanel action={action} defaults={DEFAULTS} listable />);
    const user = userEvent.setup();
    const cadence = () => screen.getByLabelText(/^Cadence/) as HTMLInputElement;
    await user.clear(cadence());
    await user.type(cadence(), "3600");
    // The same settings rendered again (a refresh that found nothing new) keep the edit.
    rerender(<SettingsPanel action={action} defaults={{ ...DEFAULTS }} listable />);
    expect(cadence().value).toBe("3600");
    await user.type(screen.getByLabelText(/^Why/), "Example reason of enough length");
    await user.click(screen.getByRole("button", { name: "Save the settings" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Save the settings" }),
    );
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Saved: cadence."));
    expect(action.mock.calls[0]?.[1].get("rendered_cadence_seconds")).toBe("7200");
    // The page renders the source as saved, paused meanwhile by someone else: the form shows it.
    const after = { ...DEFAULTS, cadenceSeconds: 3600, paused: true };
    rerender(<SettingsPanel action={action} defaults={after} listable />);
    expect(cadence().value).toBe("3600");
    expect(screen.getByRole("checkbox", { name: /^Paused/ }).getAttribute("aria-checked")).toBe(
      "true",
    );
    expect((screen.getByLabelText(/^Why/) as HTMLTextAreaElement).value).toBe("");
    expect(screen.getByRole("status").textContent).toBe("Saved: cadence.");
    await user.click(screen.getByRole("checkbox", { name: /^Enabled/ }));
    await user.type(screen.getByLabelText(/^Why/), "Example second reason, long enough");
    await user.click(screen.getByRole("button", { name: "Save the settings" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Save the settings" }),
    );
    await waitFor(() => expect(action).toHaveBeenCalledTimes(2));
    const second = action.mock.calls[1]?.[1];
    expect(second?.get("rendered_cadence_seconds")).toBe("3600");
    expect(second?.get("rendered_paused")).toBe("on");
    expect(second?.get("paused")).toBe("on");
    expect(second?.get("enabled")).toBeNull();
  });

  it("puts a refusal's field messages under their fields", async () => {
    const action = vi.fn<WriteAction<SettingsResult>>(async () => ({
      status: "error",
      fieldErrors: { cadence_seconds: ["Example cadence message"], name: ["Example name message"] },
    }));
    render(<SettingsPanel action={action} defaults={DEFAULTS} listable={false} />);
    expect(screen.getByText(/An upload-only source is never crawled/)).toBeDefined();
    const user = userEvent.setup();
    await user.clear(screen.getByLabelText(/^Cadence/));
    await user.type(screen.getByLabelText(/^Cadence/), "5");
    await user.click(screen.getByRole("checkbox", { name: /^Enabled/ }));
    await user.type(screen.getByLabelText(/^Why/), "Example reason of enough length");
    await user.click(screen.getByRole("button", { name: "Save the settings" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Save the settings" }),
    );
    await waitFor(() => expect(screen.getByText("Example cadence message")).toBeDefined());
    expect(screen.getByText("Example name message")).toBeDefined();
    expect(action.mock.calls[0]?.[1].get("enabled")).toBeNull();
  });
});

describe("FetchPanel", () => {
  it("says what the crawl switch does, asks why and shows the refusal while crawling is off", async () => {
    const action = vi.fn<WriteAction<FetchResult>>(async () => ({
      status: "error",
      problem: {
        type: "urn:compliancewatch:problem:pipeline-crawl-disabled",
        title: "Crawling is off, so nothing was fetched",
        detail: "Example detail",
        correlationId: "req-example-3",
      },
    }));
    const { container } = render(
      <FetchPanel
        action={action}
        flag={{ name: "pipeline.crawl", variable: "CW_PIPELINE_CRAWL_ENABLED" }}
      />,
    );
    expect(container.textContent).toContain("off by default");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Fetch now" }));
    const dialog = await screen.findByRole("dialog", { name: "Fetch this source now?" });
    await user.type(within(dialog).getByRole("textbox"), "Example reason of enough length");
    await user.click(within(dialog).getByRole("button", { name: "Fetch now" }));
    await waitFor(() =>
      expect(screen.getByText("Crawling is off, so nothing was fetched")).toBeDefined(),
    );
    expect(screen.getByText("req-example-3")).toBeDefined();
    expect(action.mock.calls[0]?.[1].get("reason")).toBe("Example reason of enough length");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe("readUploadAnswer", () => {
  it("reads a stored document, a refusal with its fields and stored id, and anything else", () => {
    expect(
      readUploadAnswer(202, {
        document: { documentId: "d1", title: "Example", sourceKey: "example_statutes" },
        duplicate: true,
        workflowId: "w1",
      }),
    ).toEqual({
      kind: "stored",
      documentId: "d1",
      title: "Example",
      duplicate: true,
      sourceKey: "example_statutes",
      workflowId: "w1",
    });
    expect(
      readUploadAnswer(422, {
        title: "Some fields need attention",
        errors: [
          { loc: ["body", "reason"], msg: "Example reason message" },
          { loc: ["published_on"], msg: "Example date message" },
          { loc: [], msg: "Example dropped" },
          "not an issue",
        ],
      }),
    ).toMatchObject({
      kind: "refused",
      status: 422,
      fieldErrors: { reason: ["Example reason message"], published_on: ["Example date message"] },
    });
    expect(
      readUploadAnswer(503, { title: "Stored", document_id: "d2", correlation_id: "r" }),
    ).toMatchObject({
      documentId: "d2",
      correlationId: "r",
    });
    expect(readUploadAnswer(500, null)).toMatchObject({ kind: "refused", title: "", detail: null });
    expect(readUploadAnswer(202, { document: {} })).toMatchObject({ kind: "refused", status: 202 });
  });
});

describe("UploadPanel", () => {
  const PDF = () => new File(["%PDF-1.4 Example"], "example.pdf", { type: "application/pdf" });

  function renderPanel(maxBytes = 25_000_000) {
    return render(
      <UploadPanel
        href="/api-bff/pipeline/sources/example_statutes/uploads"
        sourceName="Example statutes"
        sourceType="Statute"
        maxBytes={maxBytes}
      />,
    );
  }

  async function fill(user: ReturnType<typeof userEvent.setup>, file: File) {
    await user.upload(screen.getByLabelText(/^File/), file);
    await user.type(screen.getByLabelText(/^Title/), "Example statute");
    await user.type(screen.getByLabelText(/^Reference/), "Example Act");
    await user.selectOptions(screen.getByLabelText(/^What it is/), "statute");
    await user.type(screen.getByLabelText(/^Why/), "Example reason of enough length");
  }

  it("posts the fields first and the file last, and links the stored document", async () => {
    let body: FormData | null = null;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      body = init.body as FormData;
      return new Response(
        JSON.stringify({
          document: {
            documentId: "0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9",
            title: "Example statute",
            sourceKey: "example_statutes",
          },
          duplicate: false,
          workflowId: "pipeline-upload-1",
        }),
        { status: 202, headers: { "content-type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderPanel();
    const user = userEvent.setup();
    await fill(user, PDF());
    await user.click(screen.getByRole("button", { name: "Upload the document" }));
    const dialog = await screen.findByRole("dialog", { name: "Upload example.pdf?" });
    expect(dialog.textContent).toContain("Example statutes");
    await user.click(within(dialog).getByRole("button", { name: "Upload the document" }));
    await waitFor(() =>
      expect(container.querySelector("[data-slot='upload-done']")).not.toBeNull(),
    );
    expect(screen.getByRole("link", { name: "Open Example statute" }).getAttribute("href")).toBe(
      "/admin/pipeline/documents/0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9",
    );
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api-bff/pipeline/sources/example_statutes/uploads");
    expect([...(body as unknown as FormData).keys()]).toEqual([
      "reason",
      "document_type",
      "title",
      "external_ref",
      "file",
    ]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("refuses a file too large or of another type before sending", async () => {
    renderPanel(5);
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(screen.getByLabelText(/^File/), PDF());
    expect(screen.getByText(/larger than the pipeline takes/)).toBeDefined();
    await user.upload(
      screen.getByLabelText(/^File/),
      new File(["x"], "example.txt", { type: "text/plain" }),
    );
    expect(screen.getByText("Choose a PDF or an HTML page.")).toBeDefined();
    expect(
      (screen.getByRole("button", { name: "Upload the document" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("says a document was stored though its ingest did not start, and keeps a lost request", async () => {
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        calls += 1;
        if (calls === 1) throw new TypeError("Example connection dropped");
        return new Response(
          JSON.stringify({
            title: "Stored, but its ingest did not start",
            detail: "Example detail",
            correlation_id: "req-example-4",
            document_id: "0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9",
            errors: [{ loc: ["body", "title"], msg: "Example title message" }],
          }),
          { status: 503, headers: { "content-type": "application/problem+json" } },
        );
      }),
    );
    const { container } = renderPanel();
    const user = userEvent.setup();
    await fill(user, PDF());
    await user.click(screen.getByRole("button", { name: "Upload the document" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Upload the document",
      }),
    );
    await waitFor(() => expect(screen.getByText("No answer came back")).toBeDefined(), {
      timeout: 5000,
    });
    // Try again stays disabled until the lost request's transition settles; a click before then
    // does nothing, so wait for it (a slow runner showed the banner well before that).
    const tryAgain = () => screen.getByRole("button", { name: "Try again" }) as HTMLButtonElement;
    await waitFor(() => expect(tryAgain().disabled).toBe(false), { timeout: 5000 });
    await user.click(tryAgain());
    await waitFor(
      () => expect(screen.getByText("Stored, but its ingest did not start")).toBeDefined(),
      { timeout: 5000 },
    );
    expect(screen.getByText("req-example-4")).toBeDefined();
    expect(screen.getByText("Example title message")).toBeDefined();
    expect(container.querySelector("[data-slot='upload-stored-link']")?.getAttribute("href")).toBe(
      "/admin/pipeline/documents/0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9",
    );
    expect(calls).toBe(2);
  });
});
