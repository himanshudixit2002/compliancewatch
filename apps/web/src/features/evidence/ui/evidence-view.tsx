import { Button, EmptyState, Field, Input, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDate, formatDateTime } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  EVIDENCE_UPLOAD_FIELDS,
  evidenceCounts,
  evidenceStatusLabel,
  evidenceStatusTabs,
  evidenceTone,
  formatFileSize,
  type EvidenceItem,
  type EvidenceList,
} from "../model/evidence";
import type { EvidenceRow } from "./evidence-rows";
import { EvidenceTable } from "./evidence-table";

export interface EvidenceViewProps {
  evidence: EvidenceList;
  /**
   * Attaches the chosen file, read from EVIDENCE_UPLOAD_FIELDS.file (a server action). No route
   * accepts evidence yet, so the upload form shows only when the page passes one.
   */
  uploadAction?: (formData: FormData) => Promise<void>;
}

function evidenceRow(item: EvidenceItem): EvidenceRow {
  return {
    id: item.id,
    fileName: item.fileName,
    size: formatFileSize(item.sizeBytes),
    uploadedBy: item.uploadedBy,
    uploadedAt: item.uploadedAt,
    uploadedLabel: formatDateTime(item.uploadedAt),
    status: item.status,
    statusLabel: evidenceStatusLabel(item.status),
    statusTone: evidenceTone(item.status),
  };
}

function UploadForm({ action }: { action: (formData: FormData) => Promise<void> }) {
  return (
    <section
      aria-labelledby="evidence-upload"
      data-slot="evidence-upload"
      className="flex flex-col gap-3 rounded-md border border-line bg-surface p-4"
    >
      <h2 id="evidence-upload" className="text-lg font-semibold text-fg">
        {t("evidence.upload.title")}
      </h2>
      <form action={action} className="flex flex-wrap items-end gap-3">
        <Field
          id="evidence-file"
          label={t("evidence.upload.file")}
          description={t("evidence.upload.help")}
          required
          className="min-w-64 flex-1"
        >
          <Input type="file" name={EVIDENCE_UPLOAD_FIELDS.file} required />
        </Field>
        <Button type="submit">{t("evidence.upload.submit")}</Button>
      </form>
    </section>
  );
}

/**
 * The files attached to an obligation as evidence: how many await review, were accepted or were
 * rejected, then each file with who uploaded it and when, under review-status tabs. The upload
 * form shows only when the page passes an upload action.
 */
export function EvidenceView({ evidence, uploadAction }: EvidenceViewProps) {
  const counts = evidenceCounts(evidence.items);
  return (
    <div data-slot="evidence" className="flex flex-col gap-6">
      <PageHeader
        title={t("evidence.title", { name: evidence.obligationName })}
        description={
          evidence.dueDate === null
            ? t("evidence.intro")
            : t("evidence.introDue", { date: formatDate(evidence.dueDate) })
        }
      />
      {uploadAction === undefined ? null : <UploadForm action={uploadAction} />}
      {evidence.items.length === 0 ? (
        <EmptyState title={t("evidence.emptyTitle")} body={t("evidence.emptyBody")} />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label={t("evidence.stat.total")} value={counts.total} />
            <StatCard label={t("evidence.stat.submitted")} value={counts.submitted} tone="info" />
            <StatCard label={t("evidence.stat.accepted")} value={counts.accepted} tone="success" />
            <StatCard
              label={t("evidence.stat.rejected")}
              value={counts.rejected}
              tone={counts.rejected > 0 ? "danger" : "neutral"}
            />
          </div>
          <EvidenceTable rows={evidence.items.map(evidenceRow)} statusTabs={evidenceStatusTabs()} />
        </>
      )}
    </div>
  );
}
