"use client";

import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, useTransition } from "react";
import {
  Banner,
  Button,
  ConfirmDialog,
  DateField,
  ErrorState,
  Field,
  Input,
  Select,
  Textarea,
} from "@compliancewatch/ui";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { DOCUMENT_TYPE_LABELS, type PipelineDocumentType } from "@/shared/ui/pipeline";
import {
  REASON_MAX_LENGTH,
  REASON_MIN_LENGTH,
  UPLOAD_ACCEPT,
  UPLOAD_FORM_FIELDS,
  UPLOAD_MEDIA_TYPES,
  readUploadAnswer,
  type UploadAnswer,
} from "./source-shared";

export interface UploadPanelProps {
  /** The upload handler of this source. */
  href: string;
  sourceName: string;
  /** The source's own document type, which a document left untyped gets. */
  sourceType: string;
  /** The largest file the handler forwards, the pipeline's limit. */
  maxBytes: number;
}

const TYPES = Object.keys(DOCUMENT_TYPE_LABELS) as PipelineDocumentType[];

const ACCEPTED = /\.(pdf|html?|xhtml)$/i;

function documentHref(documentId: string): Route {
  return hrefFor(screenById("admin.pipeline.document"), { documentId });
}

/**
 * An admin's upload of a document to an upload-only source (a statute no site lists): the file,
 * a PDF or an HTML page of at most the pipeline's limit, what it is (its type, the source's when
 * left out; its title, reference and publication date) and the reason the pipeline keeps. The form
 * posts to the upload handler, which streams the file on to the pipeline; the answer is said in
 * plain words, with a link to the stored document, and the page's documents are read again. The
 * pipeline stores a document for good, so a dialog says so before anything is sent.
 */
export function UploadPanel({ href, sourceName, sourceType, maxBytes }: UploadPanelProps) {
  const id = useId();
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [type, setType] = useState("");
  const [title, setTitle] = useState("");
  const [reference, setReference] = useState("");
  const [published, setPublished] = useState("");
  const [reason, setReason] = useState("");
  const [fileError, setFileError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [answer, setAnswer] = useState<UploadAnswer | null>(null);
  const [sent, setSent] = useState<FormData | null>(null);
  const [pending, startTransition] = useTransition();
  const [count, setCount] = useState(0);
  const outcomeRef = useRef<HTMLDivElement>(null);
  const megabytes = Math.floor(maxBytes / 1_000_000);

  useEffect(() => {
    if (count > 0) outcomeRef.current?.focus();
  }, [count]);

  const choose = (chosen: File | null) => {
    setFile(chosen);
    if (chosen === null) {
      setFileError(null);
    } else if (chosen.size > maxBytes) {
      setFileError(t("adminSources.upload.tooLarge", { limit: megabytes }));
    } else if (!ACCEPTED.test(chosen.name) && !UPLOAD_MEDIA_TYPES.includes(chosen.type)) {
      setFileError(t("adminSources.upload.wrongType"));
    } else {
      setFileError(null);
    }
  };

  const post = (formData: FormData) => {
    setSent(formData);
    startTransition(async () => {
      let next: UploadAnswer;
      try {
        const response = await fetch(href, {
          method: "POST",
          body: formData,
          credentials: "same-origin",
        });
        let body: unknown = null;
        try {
          body = await response.json();
        } catch {
          body = null;
        }
        next = readUploadAnswer(response.status, body);
      } catch {
        next = { kind: "lost" };
      }
      setAnswer(next);
      setCount((value) => value + 1);
      if (next.kind === "stored" || (next.kind === "refused" && next.documentId !== null)) {
        router.refresh();
      }
    });
  };

  const submit = () => {
    if (file === null || fileError !== null) return;
    // The fields first and the file last: the handler reads the fields before it streams the file.
    const formData = new FormData();
    formData.set(UPLOAD_FORM_FIELDS.reason, reason.trim());
    if (type !== "") formData.set(UPLOAD_FORM_FIELDS.documentType, type);
    if (title.trim() !== "") formData.set(UPLOAD_FORM_FIELDS.title, title.trim());
    if (published !== "") formData.set(UPLOAD_FORM_FIELDS.publishedOn, published);
    if (reference.trim() !== "") formData.set(UPLOAD_FORM_FIELDS.externalRef, reference.trim());
    formData.set(UPLOAD_FORM_FIELDS.file, file, file.name);
    setConfirming(false);
    post(formData);
  };

  const errorOf = (field: string): string | undefined =>
    answer?.kind === "refused" ? answer.fieldErrors[field]?.[0] : undefined;
  const ready = file !== null && fileError === null && reason.trim().length >= REASON_MIN_LENGTH;

  return (
    <section
      aria-labelledby={`${id}-heading`}
      data-slot="upload-panel"
      className="flex flex-col gap-4"
    >
      <h2 id={`${id}-heading`} className="text-lg font-semibold text-fg">
        {t("adminSources.upload.title")}
      </h2>
      <p className="max-w-prose text-sm text-fg-muted">
        {t("adminSources.upload.intro", { limit: megabytes })}
      </p>
      <Field
        id={`${id}-file`}
        label={t("adminSources.upload.file")}
        description={t("adminSources.upload.fileHelp", { limit: megabytes })}
        error={fileError ?? undefined}
        required
        className="max-w-md"
      >
        <Input
          type="file"
          accept={UPLOAD_ACCEPT}
          disabled={pending}
          onChange={(event) => choose(event.target.files?.[0] ?? null)}
        />
      </Field>
      <Field
        id={`${id}-type`}
        label={t("adminSources.upload.type")}
        description={t("adminSources.upload.typeHelp")}
        error={errorOf(UPLOAD_FORM_FIELDS.documentType)}
        className="max-w-md"
      >
        <Select
          value={type}
          disabled={pending}
          onChange={(event) => setType(event.target.value)}
          options={[
            { value: "", label: t("adminSources.upload.sourceType", { type: sourceType }) },
            ...TYPES.map((value) => ({ value, label: t(DOCUMENT_TYPE_LABELS[value]) })),
          ]}
        />
      </Field>
      <Field
        id={`${id}-title`}
        label={t("adminSources.upload.documentTitle")}
        error={errorOf(UPLOAD_FORM_FIELDS.title)}
        className="max-w-2xl"
      >
        <Input
          value={title}
          disabled={pending}
          onChange={(event) => setTitle(event.target.value)}
        />
      </Field>
      <Field
        id={`${id}-reference`}
        label={t("adminSources.upload.reference")}
        description={t("adminSources.upload.referenceHelp")}
        error={errorOf(UPLOAD_FORM_FIELDS.externalRef)}
        className="max-w-md"
      >
        <Input
          value={reference}
          maxLength={200}
          disabled={pending}
          onChange={(event) => setReference(event.target.value)}
        />
      </Field>
      <DateField
        id={`${id}-published`}
        label={t("adminSources.upload.published")}
        error={errorOf(UPLOAD_FORM_FIELDS.publishedOn)}
        value={published}
        disabled={pending}
        onChange={(event) => setPublished(event.target.value)}
        className="max-w-xs"
      />
      <Field
        id={`${id}-reason`}
        label={t("adminSources.reason")}
        description={t("adminSources.reasonHelp", { min: REASON_MIN_LENGTH })}
        error={errorOf(UPLOAD_FORM_FIELDS.reason)}
        required
        className="max-w-prose"
      >
        <Textarea
          value={reason}
          maxLength={REASON_MAX_LENGTH}
          disabled={pending}
          onChange={(event) => setReason(event.target.value)}
        />
      </Field>
      <div>
        <Button
          type="button"
          disabled={!ready || pending}
          aria-busy={pending || undefined}
          onClick={() => setConfirming(true)}
        >
          {t("adminSources.upload.submit")}
        </Button>
      </div>
      <div
        ref={outcomeRef}
        tabIndex={-1}
        data-slot="upload-outcome"
        className="flex flex-col gap-2 outline-none"
      >
        {answer === null ? null : answer.kind === "lost" ? (
          <Banner
            tone="warning"
            title={t("writes.lostTitle")}
            action={
              sent === null ? null : (
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={pending}
                  aria-busy={pending || undefined}
                  onClick={() => post(sent)}
                >
                  {t("writes.tryAgain")}
                </Button>
              )
            }
          >
            {t("adminSources.upload.lost")}
          </Banner>
        ) : answer.kind === "stored" ? (
          <div role="status" data-slot="upload-done" className="flex flex-col gap-1 text-sm">
            <p className="font-medium text-fg">
              {answer.duplicate
                ? t("adminSources.upload.duplicate", { source: answer.sourceKey })
                : t("adminSources.upload.stored")}
            </p>
            <Link
              href={documentHref(answer.documentId)}
              className="text-primary underline-offset-2 hover:underline"
            >
              {t("adminSources.upload.open", {
                title: answer.title === "" ? answer.documentId : answer.title,
              })}
            </Link>
          </div>
        ) : (
          <>
            <ErrorState
              title={answer.title === "" ? t("adminSources.upload.refused") : answer.title}
              detail={answer.detail ?? undefined}
              status={answer.status}
              correlationId={answer.correlationId ?? undefined}
            />
            {answer.documentId === null ? null : (
              <Link
                href={documentHref(answer.documentId)}
                data-slot="upload-stored-link"
                className="text-sm text-primary underline-offset-2 hover:underline"
              >
                {t("adminSources.upload.openStored")}
              </Link>
            )}
          </>
        )}
      </div>
      {confirming && file !== null ? (
        <ConfirmDialog
          open
          onOpenChange={(next) => {
            if (!next) setConfirming(false);
          }}
          title={t("adminSources.upload.confirmTitle", { file: file.name })}
          description={t("adminSources.upload.confirmBody", { source: sourceName })}
          confirmLabel={t("adminSources.upload.submit")}
          cancelLabel={t("common.cancel")}
          pending={pending}
          onConfirm={submit}
        />
      ) : null}
    </section>
  );
}
