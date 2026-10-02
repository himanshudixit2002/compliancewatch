import {
  EmptyState,
  PageHeader,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDate, formatDateTime } from "@/shared/lib/dates";
import {
  evidenceTone,
  formatFileSize,
  type EvidenceList,
  type EvidenceStatus,
} from "../model/evidence";

export interface EvidenceViewProps {
  evidence: EvidenceList;
}

const STATUS_LABEL: Readonly<Record<EvidenceStatus, MessageKey>> = {
  submitted: "evidence.status.submitted",
  accepted: "evidence.status.accepted",
  rejected: "evidence.status.rejected",
};

/** The files attached to an obligation as evidence, with who uploaded them and their review. */
export function EvidenceView({ evidence }: EvidenceViewProps) {
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
      {evidence.items.length === 0 ? (
        <EmptyState title={t("evidence.emptyTitle")} body={t("evidence.emptyBody")} />
      ) : (
        <Table>
          <TableCaption className="sr-only">{t("evidence.tableCaption")}</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("evidence.column.file")}</TableHead>
              <TableHead>{t("evidence.column.size")}</TableHead>
              <TableHead>{t("evidence.column.uploadedBy")}</TableHead>
              <TableHead>{t("evidence.column.uploadedAt")}</TableHead>
              <TableHead>{t("evidence.column.status")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {evidence.items.map((item) => (
              <TableRow key={item.id} data-item={item.id}>
                <TableCell className="font-medium text-fg">{item.fileName}</TableCell>
                <TableCell className="text-fg-muted">{formatFileSize(item.sizeBytes)}</TableCell>
                <TableCell>{item.uploadedBy}</TableCell>
                <TableCell className="text-fg-muted">
                  <time dateTime={item.uploadedAt}>{formatDateTime(item.uploadedAt)}</time>
                </TableCell>
                <TableCell>
                  <StatusChip
                    status={item.status}
                    tone={evidenceTone(item.status)}
                    label={t(STATUS_LABEL[item.status])}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
