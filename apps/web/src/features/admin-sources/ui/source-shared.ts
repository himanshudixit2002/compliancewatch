/**
 * What the source pages' client panels and their server actions share, in the ui directory so the
 * client components may import it: the field names, the limits the pipeline applies (checked again
 * in the actions and by the pipeline, which owns the rules), and the shapes of an answer.
 */
export const SETTINGS_FIELDS = {
  name: "name",
  cadence: "cadence_seconds",
  enabled: "enabled",
  paused: "paused",
  parameters: "parameters",
  reason: "reason",
} as const;

/**
 * The settings the form was rendered with, posted beside the edited ones as hidden fields: the
 * action sends only what the admin changed from these, and refuses a change to a setting someone
 * else changed since.
 */
export const SETTINGS_RENDERED_FIELDS = {
  name: "rendered_name",
  cadence: "rendered_cadence_seconds",
  enabled: "rendered_enabled",
  paused: "rendered_paused",
  parameters: "rendered_parameters",
} as const;

export const FETCH_FIELDS = { reason: "reason" } as const;

/** The fewest characters of a reason, once trimmed: the pipeline's rule for every write. */
export const REASON_MIN_LENGTH = 10;

/** The longest reason the pipeline's audit entry keeps. */
export const REASON_MAX_LENGTH = 2000;

/** A source's name, 1 to 200 characters. */
export const NAME_MAX_LENGTH = 200;

/** A cadence from a minute to 31 days, in seconds. */
export const CADENCE_MIN_SECONDS = 60;
export const CADENCE_MAX_SECONDS = 2_678_400;

/** A checkbox's value when it is ticked. */
export const CHECKED = "on";

/** A rendered switch that was off (an unticked box sends nothing; a rendered one says so). */
export const UNCHECKED = "off";

/** What a settings change answered: the sentence to announce and the settings it changed. */
export interface SettingsResult {
  message: string;
  changed: readonly string[];
}

/** What a fetch answered: the sentence to announce. */
export interface FetchResult {
  message: string;
}

/** Whether a write may be offered, and why not (the refusal names the role or the variable). */
export type AccessView = { allowed: true } | { allowed: false; title: string; detail?: string };

/**
 * The settings form's starting values: the source as the pipeline held it when the page rendered.
 * The form posts them back as its hidden fields (`SETTINGS_RENDERED_FIELDS`).
 */
export interface SettingsDefaults {
  name: string;
  cadenceSeconds: number;
  enabled: boolean;
  paused: boolean;
  /** The parameters as indented JSON. */
  parameters: string;
}

/** The upload form's field names: the pipeline's own. */
export const UPLOAD_FORM_FIELDS = {
  file: "file",
  reason: "reason",
  title: "title",
  publishedOn: "published_on",
  externalRef: "external_ref",
  documentType: "document_type",
} as const;

/** The media types the pipeline takes: a PDF or an HTML page. */
export const UPLOAD_MEDIA_TYPES: readonly string[] = [
  "application/pdf",
  "text/html",
  "application/xhtml+xml",
];

/** The file types the pipeline takes, for the file picker. */
export const UPLOAD_ACCEPT =
  "application/pdf,.pdf,text/html,.html,.htm,application/xhtml+xml,.xhtml";

/** The upload handler's answer, as the form reads it. */
export type UploadAnswer =
  | {
      kind: "stored";
      documentId: string;
      title: string;
      duplicate: boolean;
      /** The source the bytes were stored under first (another source's for a duplicate). */
      sourceKey: string;
      workflowId: string;
    }
  | {
      kind: "refused";
      status: number;
      title: string;
      detail: string | null;
      correlationId: string | null;
      /** The document stored when the ingest could not start. */
      documentId: string | null;
      /** Messages per field, from a 422. */
      fieldErrors: Readonly<Record<string, readonly string[]>>;
    }
  | { kind: "lost" };

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

/**
 * The handler's answer read: a 202 with the stored document, or a problem with its title, detail,
 * correlation id, the stored document's id (a 503 whose ingest did not start) and its field
 * errors. A body that is neither reads as a refusal of its status.
 */
export function readUploadAnswer(status: number, body: unknown): UploadAnswer {
  const data = record(body);
  if (status === 202 && data !== null) {
    const document = record(data.document);
    if (document !== null && typeof document.documentId === "string") {
      return {
        kind: "stored",
        documentId: document.documentId,
        title: typeof document.title === "string" ? document.title : "",
        duplicate: data.duplicate === true,
        sourceKey: typeof document.sourceKey === "string" ? document.sourceKey : "",
        workflowId: typeof data.workflowId === "string" ? data.workflowId : "",
      };
    }
  }
  const fieldErrors: Record<string, string[]> = {};
  const errors = Array.isArray(data?.errors) ? data.errors : [];
  for (const entry of errors) {
    const issue = record(entry);
    const loc = Array.isArray(issue?.loc) ? issue.loc.map(String) : [];
    const field = loc.length > 1 && loc[0] === "body" ? loc.slice(1).join(".") : loc.join(".");
    const message = text(issue?.msg);
    if (field !== "" && message !== null) (fieldErrors[field] ??= []).push(message);
  }
  return {
    kind: "refused",
    status,
    title: text(data?.title) ?? "",
    detail: text(data?.detail),
    correlationId: text(data?.correlation_id),
    documentId: text(data?.document_id),
    fieldErrors,
  };
}
