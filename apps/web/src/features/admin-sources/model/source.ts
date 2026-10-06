import type { Tone } from "@compliancewatch/ui";
import type { Page, PipelineSource, SourceEdit, StoredDocument } from "@/entities/pipeline/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { formatDate, formatDateTime } from "@/shared/lib/dates";
import { withQuery } from "@/shared/lib/url";
import { documentTypeLabel } from "@/shared/ui/pipeline";
import {
  CADENCE_MAX_SECONDS,
  CADENCE_MIN_SECONDS,
  CHECKED,
  FETCH_FIELDS,
  NAME_MAX_LENGTH,
  REASON_MAX_LENGTH,
  REASON_MIN_LENGTH,
  SETTINGS_FIELDS,
  type SettingsDefaults,
} from "../ui/source-shared";
import {
  cadenceText,
  formatCount,
  freshnessLabel,
  freshnessText,
  freshnessTone,
  runSummary,
  sourceStatusLabel,
  sourceStatusTone,
  switchesText,
  type RunSummary,
} from "./sources";

/**
 * One source's page: its facts and settings as the pipeline holds them, its stored documents a
 * page at a time (newest publication first, by the pipeline's cursor in the address), and the
 * settings form's parse, which sends only what changed.
 */
export const SOURCE_PARAMS = { cursor: "cursor" } as const;

/** Documents a page shows. */
export const DOCUMENT_PAGE_SIZE = 25;

/** The latest runs the page shows; the pipeline page lists every run of the source. */
export const SOURCE_RUNS_SHOWN = 10;

/** The pipeline's cursor is opaque text of at most 512 characters. */
export function readCursor(value: string | string[] | undefined): string | null {
  const raw = (Array.isArray(value) ? value[0] : value)?.trim() ?? "";
  return raw === "" || raw.length > 512 ? null : raw;
}

export interface SourceFacts {
  key: string;
  name: string;
  adapterType: string;
  regulator: string | null;
  site: string | null;
  docType: string;
  listable: boolean;
  switches: string;
  status: { label: string; tone: Tone };
  cadence: string;
  /** The detail is null before the first listing, which the label says already. */
  freshness: { label: string; tone: Tone; detail: string | null };
  lastListed: { text: string; iso: string } | null;
  watermark: string | null;
  lastError: string;
  documents: string;
  latestRun: RunSummary | null;
  created: string;
  updated: string;
  parameters: Readonly<Record<string, unknown>>;
}

export function sourceFacts(source: PipelineSource): SourceFacts {
  return {
    key: source.key,
    name: source.name,
    adapterType: source.adapterType,
    regulator: source.regulator,
    site: source.site,
    docType: documentTypeLabel(source.docType),
    listable: source.listable,
    switches: switchesText(source),
    status: { label: sourceStatusLabel(source.status), tone: sourceStatusTone(source.status) },
    cadence: cadenceText(source.cadenceSeconds),
    freshness: {
      label: freshnessLabel(source.freshness.state),
      tone: freshnessTone(source.freshness.state),
      detail: freshnessText(source.freshness),
    },
    lastListed:
      source.lastFetchAt === null
        ? null
        : { text: formatDateTime(source.lastFetchAt), iso: source.lastFetchAt },
    watermark: source.watermark === null ? null : formatDate(source.watermark),
    lastError: source.lastError,
    documents: formatCount(source.documentCount),
    latestRun: source.latestRun === null ? null : runSummary(source.latestRun),
    created: formatDateTime(source.createdAt),
    updated: formatDateTime(source.updatedAt),
    parameters: source.parameters,
  };
}

export function settingsDefaults(source: PipelineSource): SettingsDefaults {
  return {
    name: source.name,
    cadenceSeconds: source.cadenceSeconds,
    enabled: source.enabled,
    paused: source.paused,
    parameters: JSON.stringify(source.parameters, null, 2),
  };
}

const CONTENT_LABELS: Readonly<Record<string, string>> = {
  "application/pdf": "PDF",
  "text/html": "HTML",
  "application/xhtml+xml": "XHTML",
};

/** "PDF", "HTML" or the media type as stored. */
export function contentLabel(contentType: string): string {
  const base = (contentType.split(";")[0] ?? "").trim().toLowerCase();
  return CONTENT_LABELS[base] ?? base;
}

/** "512 bytes", "20.5 KB", "3.2 MB": decimal units, as the pipeline states its upload limit. */
export function formatBytes(bytes: number): string {
  if (bytes < 1000) return t("adminSources.size.bytes", { count: bytes });
  if (bytes < 1_000_000) {
    return t("adminSources.size.kilobytes", { count: Math.round(bytes / 100) / 10 });
  }
  return t("adminSources.size.megabytes", { count: Math.round(bytes / 100_000) / 10 });
}

export interface DocumentRow {
  documentId: string;
  title: string;
  externalRef: string;
  href: string;
  rawHref: string;
  published: string | null;
  fetched: string;
  fetchedIso: string;
  status: string;
  /** The uploader's type, or that the source's applies. */
  type: string;
  content: string;
  parser: string | null;
}

/** The page of one stored document, and the handler that streams its bytes. */
export function documentHref(documentId: string): string {
  return hrefFor(screenById("admin.pipeline.document"), { documentId });
}

export function rawHref(documentId: string): string {
  return hrefFor(screenById("system.raw-document"), { documentId });
}

export function documentRow(document: StoredDocument): DocumentRow {
  return {
    documentId: document.documentId,
    title:
      document.title !== ""
        ? document.title
        : document.externalRef !== ""
          ? document.externalRef
          : t("adminSources.documents.untitled"),
    externalRef: document.externalRef,
    href: documentHref(document.documentId),
    rawHref: rawHref(document.documentId),
    published: document.publishedOn === null ? null : formatDate(document.publishedOn),
    fetched: formatDateTime(document.fetchedAt),
    fetchedIso: document.fetchedAt,
    status: document.status,
    type:
      document.uploaderType === null
        ? t("adminSources.documents.sourceType")
        : documentTypeLabel(document.uploaderType),
    content: t("adminSources.documents.content", {
      type: contentLabel(document.contentType),
      size: formatBytes(document.size),
    }),
    parser: document.parserVersion === "" ? null : document.parserVersion,
  };
}

export interface DocumentsView {
  rows: DocumentRow[];
  nextHref: string | null;
  firstHref: string | null;
  /** Whether this page is a later one (an empty later page says so). */
  later: boolean;
}

export function documentsView(
  pathname: string,
  cursor: string | null,
  page: Page<StoredDocument>,
): DocumentsView {
  return {
    rows: page.items.map(documentRow),
    nextHref:
      page.nextCursor === null
        ? null
        : withQuery(pathname, { [SOURCE_PARAMS.cursor]: page.nextCursor }),
    firstHref: cursor === null ? null : pathname,
    later: cursor !== null,
  };
}

// ---- The forms ---------------------------------------------------------------------------------

function textOf(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

/** A reason of 10 to 2000 characters once trimmed, or the message for its field. */
export function reasonOf(
  formData: FormData,
  field: string = FETCH_FIELDS.reason,
): { ok: true; reason: string } | { ok: false; fieldErrors: FieldErrors } {
  const reason = textOf(formData, field).trim();
  if (reason.length < REASON_MIN_LENGTH) {
    return {
      ok: false,
      fieldErrors: { [field]: [t("adminSources.error.reasonShort", { min: REASON_MIN_LENGTH })] },
    };
  }
  if (reason.length > REASON_MAX_LENGTH) {
    return {
      ok: false,
      fieldErrors: { [field]: [t("adminSources.error.reasonLong", { max: REASON_MAX_LENGTH })] },
    };
  }
  return { ok: true, reason };
}

/** Deep equality of JSON values, keys in any order. */
export function sameJson(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((item, index) => sameJson(item, b[index]));
  }
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  const keys = Object.keys(left);
  return (
    keys.length === Object.keys(right).length &&
    keys.every((key) => Object.hasOwn(right, key) && sameJson(left[key], right[key]))
  );
}

/** The labels of the settings a change names, in the form's order. */
export const SETTING_LABELS = {
  name: "adminSources.settings.name",
  cadenceSeconds: "adminSources.settings.cadence",
  enabled: "adminSources.settings.enabled",
  paused: "adminSources.settings.paused",
  parameters: "adminSources.settings.parameters",
} as const;

export type ParsedSettings =
  | { ok: true; edit: SourceEdit; reason: string; changed: (keyof typeof SETTING_LABELS)[] }
  | { ok: false; fieldErrors: FieldErrors; formError?: string };

/**
 * The settings form against the source as the pipeline holds it now: each field's shape (a name
 * of 1 to 200 characters, a whole cadence from a minute to 31 days, the parameters as a JSON
 * object), the reason, and only the settings that differ, so an unchanged form sends nothing.
 */
export function parseSettings(formData: FormData, current: PipelineSource): ParsedSettings {
  const errors: Record<string, string[]> = {};
  const name = textOf(formData, SETTINGS_FIELDS.name).trim();
  if (name === "" || name.length > NAME_MAX_LENGTH) {
    errors[SETTINGS_FIELDS.name] = [t("adminSources.error.name", { max: NAME_MAX_LENGTH })];
  }
  const cadenceInput = textOf(formData, SETTINGS_FIELDS.cadence).trim();
  const cadence = /^\d+$/.test(cadenceInput) ? Number(cadenceInput) : Number.NaN;
  if (!(cadence >= CADENCE_MIN_SECONDS && cadence <= CADENCE_MAX_SECONDS)) {
    errors[SETTINGS_FIELDS.cadence] = [
      t("adminSources.error.cadence", { min: CADENCE_MIN_SECONDS, max: CADENCE_MAX_SECONDS }),
    ];
  }
  const enabled = textOf(formData, SETTINGS_FIELDS.enabled) === CHECKED;
  const paused = textOf(formData, SETTINGS_FIELDS.paused) === CHECKED;
  let parameters: Record<string, unknown> | null = null;
  const parametersText = textOf(formData, SETTINGS_FIELDS.parameters).trim();
  try {
    const parsed: unknown = JSON.parse(parametersText === "" ? "{}" : parametersText);
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      parameters = parsed as Record<string, unknown>;
    }
  } catch {
    parameters = null;
  }
  if (parameters === null)
    errors[SETTINGS_FIELDS.parameters] = [t("adminSources.error.parameters")];
  const reason = reasonOf(formData, SETTINGS_FIELDS.reason);
  if (!reason.ok) Object.assign(errors, reason.fieldErrors);
  if (Object.keys(errors).length > 0 || !reason.ok || parameters === null) {
    return { ok: false, fieldErrors: errors };
  }
  const edit: SourceEdit = {};
  const changed: (keyof typeof SETTING_LABELS)[] = [];
  if (name !== current.name) {
    edit.name = name;
    changed.push("name");
  }
  if (cadence !== current.cadenceSeconds) {
    edit.cadenceSeconds = cadence;
    changed.push("cadenceSeconds");
  }
  if (enabled !== current.enabled) {
    edit.enabled = enabled;
    changed.push("enabled");
  }
  if (paused !== current.paused) {
    edit.paused = paused;
    changed.push("paused");
  }
  if (!sameJson(parameters, current.parameters)) {
    edit.parameters = parameters;
    changed.push("parameters");
  }
  if (changed.length === 0) {
    return { ok: false, fieldErrors: {}, formError: t("adminSources.error.nothingChanged") };
  }
  return { ok: true, edit, reason: reason.reason, changed };
}

/** "the name and the cadence": the settings a change named, in words. */
export function changedText(changed: readonly (keyof typeof SETTING_LABELS)[]): string {
  const labels = changed.map((key) => t(SETTING_LABELS[key]).toLowerCase());
  if (labels.length <= 1) return labels.join("");
  return t("adminSources.settings.andList", {
    first: labels.slice(0, -1).join(", "),
    last: labels.at(-1) ?? "",
  });
}
