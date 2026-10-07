import {
  DOCUMENT_TYPES,
  RETRY_STAGES,
  type DocumentDetail,
  type DocumentRetry,
  type DocumentType,
  type RetryStage,
} from "@/entities/pipeline/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { formatDate, formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { documentTypeLabel, sourceHref } from "@/shared/ui/pipeline";
import { REASON_MAX_LENGTH, REASON_MIN_LENGTH, RETRY_FIELDS } from "../ui/pipeline-shared";
import {
  classificationView,
  documentTitle,
  extractionView,
  type ClassificationView,
  type ExtractionView,
} from "./operations";

/**
 * A stored document's page: the record (where it was listed or uploaded, its digest, its parse),
 * how the pipeline reads it (its type, its classification by the detector or a person, its rule
 * extraction by the current prompt), the retries people asked for, and for an admin the retry.
 */
const STAGE_LABELS: Readonly<Record<RetryStage, MessageKey>> = {
  parse: "pipelineDocument.stage.parse",
  classify: "pipelineDocument.stage.classify",
  extract: "pipelineDocument.stage.extract",
};

export function stageLabel(stage: string): string {
  return Object.hasOwn(STAGE_LABELS, stage)
    ? t(STAGE_LABELS[stage as RetryStage])
    : humanise(stage);
}

export interface RetryRow {
  attempt: number;
  stage: string;
  docType: string | null;
  reason: string;
  requestedBy: string | null;
  at: string;
  atIso: string;
  workflowId: string;
}

export function retryRow(retry: DocumentRetry, userId: string | null): RetryRow {
  return {
    attempt: retry.attempt,
    stage: stageLabel(retry.stage),
    docType: retry.docType === null ? null : documentTypeLabel(retry.docType),
    reason: retry.reason,
    requestedBy:
      retry.requestedBy === null
        ? null
        : retry.requestedBy === userId
          ? t("adminPipeline.you")
          : retry.requestedBy,
    at: formatDateTime(retry.requestedAt),
    atIso: retry.requestedAt,
    workflowId: retry.workflowId,
  };
}

export interface DocumentPageView {
  documentId: string;
  title: string;
  externalRef: string;
  sourceKey: string;
  sourceHref: string;
  /** Where it was listed, or `upload://<source>/<sha256>` for an upload. */
  sourceUrl: string;
  rawHref: string;
  published: string | null;
  fetched: string;
  fetchedIso: string;
  status: string;
  readAs: string;
  uploaderType: string | null;
  contentType: string;
  size: number;
  sha256: string;
  storageKey: string;
  parser: string | null;
  classification: ClassificationView | null;
  extraction: ExtractionView | null;
  retries: RetryRow[];
  /** The type the pipeline reads it as, for the retry's default. */
  readAsType: DocumentType | null;
}

export function documentPageView(
  document: DocumentDetail,
  userId: string | null,
): DocumentPageView {
  return {
    documentId: document.documentId,
    title: documentTitle(document),
    externalRef: document.externalRef,
    sourceKey: document.sourceKey,
    sourceHref: sourceHref(document.sourceKey),
    sourceUrl: document.sourceUrl,
    rawHref: hrefFor(screenById("system.raw-document"), { documentId: document.documentId }),
    published: document.publishedOn === null ? null : formatDate(document.publishedOn),
    fetched: formatDateTime(document.fetchedAt),
    fetchedIso: document.fetchedAt,
    status: document.status,
    readAs: documentTypeLabel(document.readAs),
    uploaderType: document.uploaderType === null ? null : documentTypeLabel(document.uploaderType),
    contentType: document.contentType,
    size: document.size,
    sha256: document.sha256,
    storageKey: document.storageKey,
    parser: document.parserVersion === "" ? null : document.parserVersion,
    classification:
      document.classification === null ? null : classificationView(document.classification, userId),
    extraction: document.extraction === null ? null : extractionView(document.extraction),
    retries: [...document.retries].reverse().map((retry) => retryRow(retry, userId)),
    readAsType: document.readAs,
  };
}

function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

/** A reason of 10 to 2000 characters once trimmed, or the message for its field. */
export function reasonOf(
  formData: FormData,
  field: string,
): { ok: true; reason: string } | { ok: false; fieldErrors: FieldErrors } {
  const reason = text(formData, field).trim();
  if (reason.length < REASON_MIN_LENGTH) {
    return {
      ok: false,
      fieldErrors: { [field]: [t("adminPipeline.error.reasonShort", { min: REASON_MIN_LENGTH })] },
    };
  }
  if (reason.length > REASON_MAX_LENGTH) {
    return {
      ok: false,
      fieldErrors: { [field]: [t("adminPipeline.error.reasonLong", { max: REASON_MAX_LENGTH })] },
    };
  }
  return { ok: true, reason };
}

export type ParsedRetry =
  | { ok: true; stage: RetryStage; docType: DocumentType | null; reason: string }
  | { ok: false; fieldErrors: FieldErrors };

/** The retry form: a stage, an optional type (empty: its classification stands) and the reason. */
export function parseRetry(formData: FormData): ParsedRetry {
  const errors: Record<string, string[]> = {};
  const stageValue = text(formData, RETRY_FIELDS.stage);
  const stage = (RETRY_STAGES as readonly string[]).includes(stageValue)
    ? (stageValue as RetryStage)
    : null;
  if (stage === null) errors[RETRY_FIELDS.stage] = [t("pipelineDocument.error.stage")];
  const typeValue = text(formData, RETRY_FIELDS.docType);
  const docType = (DOCUMENT_TYPES as readonly string[]).includes(typeValue)
    ? (typeValue as DocumentType)
    : null;
  if (typeValue !== "" && docType === null) {
    errors[RETRY_FIELDS.docType] = [t("pipelineDocument.error.type")];
  }
  const reason = reasonOf(formData, RETRY_FIELDS.reason);
  if (!reason.ok) Object.assign(errors, reason.fieldErrors);
  if (stage === null || !reason.ok || Object.keys(errors).length > 0) {
    return { ok: false, fieldErrors: errors };
  }
  return { ok: true, stage, docType, reason: reason.reason };
}
