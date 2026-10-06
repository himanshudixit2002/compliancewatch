import { describe, expect, it } from "vitest";
import { sourceFromDto, storedDocumentFromDto } from "@/entities/pipeline/mappers";
import { DOCUMENT_ID, documentDto, sourceDto, uploadSourceDto } from "@/test/pipeline-fixture";
import { SETTINGS_FIELDS, SETTINGS_RENDERED_FIELDS } from "../ui/source-shared";
import {
  changedMeanwhile,
  changedMeanwhileText,
  changedText,
  contentLabel,
  documentRow,
  documentsView,
  formatBytes,
  parseSettings,
  readCursor,
  reasonOf,
  renderedSettingsOf,
  sameJson,
  settingsDefaults,
  sourceFacts,
} from "./source";

const REASON = "Example reason of enough length";

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [name, value] of Object.entries(values)) data.set(name, value);
  return data;
}

const SOURCE = sourceFromDto(sourceDto());

/** What the form posts for the settings it was rendered with: SOURCE's, as the page shows them. */
const RENDERED: Record<string, string> = {
  [SETTINGS_RENDERED_FIELDS.name]: SOURCE.name,
  [SETTINGS_RENDERED_FIELDS.cadence]: String(SOURCE.cadenceSeconds),
  [SETTINGS_RENDERED_FIELDS.enabled]: "on",
  [SETTINGS_RENDERED_FIELDS.paused]: "off",
  [SETTINGS_RENDERED_FIELDS.parameters]: JSON.stringify(SOURCE.parameters, null, 2),
};

/** The form as the page renders it for SOURCE, changed by `overrides`. */
function settings(overrides: Record<string, string | null> = {}): FormData {
  const values: Record<string, string | null> = {
    [SETTINGS_FIELDS.name]: SOURCE.name,
    [SETTINGS_FIELDS.cadence]: String(SOURCE.cadenceSeconds),
    [SETTINGS_FIELDS.enabled]: "on",
    [SETTINGS_FIELDS.paused]: null,
    [SETTINGS_FIELDS.parameters]: JSON.stringify(SOURCE.parameters, null, 2),
    [SETTINGS_FIELDS.reason]: REASON,
    ...RENDERED,
    ...overrides,
  };
  return form(
    Object.fromEntries(
      Object.entries(values).filter((entry): entry is [string, string] => entry[1] !== null),
    ),
  );
}

describe("the source's page", () => {
  it("gives the facts of a listing source and an upload-only one", () => {
    expect(sourceFacts(SOURCE)).toMatchObject({
      key: "example_notices",
      listable: true,
      cadence: "Every 2 h",
      documents: "42",
      status: { label: "Healthy", tone: "success" },
      freshness: { label: "Fresh" },
      watermark: "1 Jan 2000",
      parameters: { listing: "notices" },
    });
    expect(sourceFacts(sourceFromDto(uploadSourceDto()))).toMatchObject({
      listable: false,
      lastListed: null,
      latestRun: null,
      watermark: null,
    });
    expect(settingsDefaults(SOURCE)).toEqual({
      name: "Example notices",
      cadenceSeconds: 7200,
      enabled: true,
      paused: false,
      parameters: '{\n  "listing": "notices"\n}',
    });
  });

  it("words a stored document with its links, type and size", () => {
    const row = documentRow(storedDocumentFromDto(documentDto()));
    expect(row).toMatchObject({
      title: "Example notice 1",
      href: `/admin/pipeline/documents/${DOCUMENT_ID}`,
      rawHref: `/api-bff/pipeline/documents/${DOCUMENT_ID}/raw`,
      published: "1 Jan 2000",
      type: "The source's type",
      content: "PDF, 20.5 KB",
      parser: "pdf@1",
    });
    const bare = documentRow(
      storedDocumentFromDto(
        documentDto({
          title: "",
          external_ref: "",
          published_on: null,
          parser_version: "",
          doc_type: "statute",
        }),
      ),
    );
    expect(bare).toMatchObject({
      title: "Untitled document",
      published: null,
      parser: null,
      type: "Statute",
    });
    expect(
      documentRow(storedDocumentFromDto(documentDto({ title: "", external_ref: "Example 1/2000" })))
        .title,
    ).toBe("Example 1/2000");
    expect(contentLabel("text/html; charset=utf-8")).toBe("HTML");
    expect(contentLabel("application/xhtml+xml")).toBe("XHTML");
    expect(contentLabel("image/png")).toBe("image/png");
    expect(formatBytes(512)).toBe("512 bytes");
    expect(formatBytes(3_200_000)).toBe("3.2 MB");
  });

  it("pages the documents by the pipeline's cursor", () => {
    const page = { items: [storedDocumentFromDto(documentDto())], nextCursor: "next+1" };
    const first = documentsView("/admin/sources/example_notices", null, page);
    expect(first).toMatchObject({
      nextHref: "/admin/sources/example_notices?cursor=next%2B1",
      firstHref: null,
      later: false,
    });
    const later = documentsView("/admin/sources/example_notices", "abc", {
      items: [],
      nextCursor: null,
    });
    expect(later).toMatchObject({
      nextHref: null,
      firstHref: "/admin/sources/example_notices",
      later: true,
    });
    expect(readCursor(" abc ")).toBe("abc");
    expect(readCursor(["abc", "def"])).toBe("abc");
    expect(readCursor(undefined)).toBeNull();
    expect(readCursor("x".repeat(513))).toBeNull();
  });
});

describe("the forms", () => {
  it("takes a reason of 10 to 2000 characters", () => {
    expect(reasonOf(form({ reason: `  ${REASON}  ` }))).toEqual({ ok: true, reason: REASON });
    expect(reasonOf(form({ reason: "short" })).ok).toBe(false);
    expect(reasonOf(form({ reason: "x".repeat(2001) })).ok).toBe(false);
    expect(reasonOf(new FormData()).ok).toBe(false);
  });

  it("compares JSON values whatever the key order", () => {
    expect(sameJson({ a: 1, b: [1, { c: 2 }] }, { b: [1, { c: 2 }], a: 1 })).toBe(true);
    expect(sameJson({ a: 1 }, { a: 1, b: 2 })).toBe(false);
    expect(sameJson([1, 2], [2, 1])).toBe(false);
    expect(sameJson([1], { 0: 1 })).toBe(false);
    expect(sameJson(null, {})).toBe(false);
    expect(sameJson("x", "x")).toBe(true);
  });

  it("sends only the settings that differ from what the form showed", () => {
    const parsed = parseSettings(
      settings({
        [SETTINGS_FIELDS.name]: " Example renamed ",
        [SETTINGS_FIELDS.cadence]: "3600",
        [SETTINGS_FIELDS.enabled]: null,
        [SETTINGS_FIELDS.paused]: "on",
        [SETTINGS_FIELDS.parameters]: '{"listing": "circulars"}',
      }),
    );
    expect(parsed).toEqual({
      ok: true,
      reason: REASON,
      changed: ["name", "cadenceSeconds", "enabled", "paused", "parameters"],
      edit: {
        name: "Example renamed",
        cadenceSeconds: 3600,
        enabled: false,
        paused: true,
        parameters: { listing: "circulars" },
      },
      rendered: {
        name: "Example notices",
        cadenceSeconds: 7200,
        enabled: true,
        paused: false,
        parameters: { listing: "notices" },
      },
    });
    const parameters = parseSettings(
      settings({ [SETTINGS_FIELDS.parameters]: '{ "listing" : "notices" }' }),
    );
    expect(parameters).toMatchObject({
      ok: false,
      formError: expect.stringMatching(/^Nothing to save/),
    });
    const empty = parseSettings(
      settings({
        [SETTINGS_FIELDS.parameters]: "",
        [SETTINGS_RENDERED_FIELDS.parameters]: "{}",
      }),
    );
    expect(empty.ok).toBe(false);
  });

  it("leaves alone a setting the admin did not touch, whatever it was rendered as", () => {
    // The form was rendered paused; the admin changed only the cadence, so paused is not sent
    // even though the form posts it, and a pause or a resume made meanwhile stands.
    const parsed = parseSettings(
      settings({
        [SETTINGS_FIELDS.paused]: "on",
        [SETTINGS_RENDERED_FIELDS.paused]: "on",
        [SETTINGS_FIELDS.cadence]: "3600",
      }),
    );
    expect(parsed).toMatchObject({
      ok: true,
      changed: ["cadenceSeconds"],
      edit: { cadenceSeconds: 3600 },
    });
    expect(parsed.ok && Object.keys(parsed.edit)).toEqual(["cadenceSeconds"]);
  });

  it("refuses a form that does not say what it showed", () => {
    for (const missing of Object.values(SETTINGS_RENDERED_FIELDS)) {
      const form = settings({ [SETTINGS_FIELDS.cadence]: "3600", [missing]: null });
      expect(parseSettings(form), missing).toMatchObject({
        ok: false,
        formError: expect.stringMatching(/^The form did not say which settings it showed/),
      });
    }
    expect(renderedSettingsOf(settings({ [SETTINGS_RENDERED_FIELDS.enabled]: "yes" }))).toBeNull();
    expect(renderedSettingsOf(settings({ [SETTINGS_RENDERED_FIELDS.cadence]: "1.5" }))).toBeNull();
    expect(
      renderedSettingsOf(settings({ [SETTINGS_RENDERED_FIELDS.parameters]: "[1]" })),
    ).toBeNull();
    expect(renderedSettingsOf(settings())).toEqual({
      name: "Example notices",
      cadenceSeconds: 7200,
      enabled: true,
      paused: false,
      parameters: { listing: "notices" },
    });
  });

  it("finds the changed settings someone else changed since the form rendered, and words them", () => {
    const parsed = parseSettings(
      settings({
        [SETTINGS_FIELDS.name]: "Example renamed",
        [SETTINGS_FIELDS.cadence]: "3600",
        [SETTINGS_FIELDS.enabled]: null,
        [SETTINGS_FIELDS.paused]: "on",
        [SETTINGS_FIELDS.parameters]: '{"listing": "circulars"}',
      }),
    );
    if (!parsed.ok) throw new Error("the form should parse");
    expect(changedMeanwhile(parsed.changed, parsed.rendered, SOURCE)).toEqual([]);
    const live = sourceFromDto(
      sourceDto({
        name: "Example notices, renamed meanwhile",
        cadence_seconds: 14_400,
        enabled: false,
        paused: true,
        parameters: { listing: "orders" },
      }),
    );
    const meanwhile = changedMeanwhile(parsed.changed, parsed.rendered, live);
    expect(meanwhile).toEqual(["name", "cadenceSeconds", "enabled", "paused", "parameters"]);
    expect(meanwhile.map((setting) => changedMeanwhileText(setting, live))).toEqual([
      'The name changed meanwhile: it is now "Example notices, renamed meanwhile".',
      "The cadence changed meanwhile: it is now 14400 seconds (4 h).",
      "The enabled switch changed meanwhile: it is now off.",
      "The paused switch changed meanwhile: it is now on.",
      'The parameters changed meanwhile: they are now {"listing":"orders"}.',
    ]);
    // Only the settings the admin changed are looked at: a pause made meanwhile, with only the
    // cadence changed in the form, is no conflict and is not sent.
    const cadenceOnly = parseSettings(settings({ [SETTINGS_FIELDS.cadence]: "3600" }));
    if (!cadenceOnly.ok) throw new Error("the form should parse");
    const pausedMeanwhile = sourceFromDto(sourceDto({ paused: true }));
    expect(changedMeanwhile(cadenceOnly.changed, cadenceOnly.rendered, pausedMeanwhile)).toEqual(
      [],
    );
    expect(changedMeanwhileText("enabled", sourceFromDto(sourceDto({ enabled: true })))).toBe(
      "The enabled switch changed meanwhile: it is now on.",
    );
  });

  it("names the settings a change made", () => {
    expect(changedText(["paused"])).toBe("paused");
    expect(changedText(["name", "cadenceSeconds"])).toBe("name and cadence");
    expect(changedText(["name", "cadenceSeconds", "parameters"])).toBe(
      "name, cadence and parameters",
    );
  });
});
