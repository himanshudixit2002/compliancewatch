import {
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

/** One task as the table shows it (the business model's ReviewTaskRow, structurally). */
export interface ReviewTasksTableRow {
  id: string;
  attributeLabel: string;
  reasonLabel: string;
  asOfFy: string | null;
  openedAt: string;
  open: boolean;
  statusLabel: string;
  nodeName: string;
}

export interface ReviewTasksTableProps {
  rows: readonly ReviewTasksTableRow[];
  caption: string;
  /** Leaves out the status column where every row is open. */
  showStatus?: boolean;
}

/**
 * Review tasks as a table: the attribute, why the task is open (the service's reason worded for
 * the owner), the year, when it opened in IST, the node it is on, and whether it is still open.
 * The web app only lists them; an analyst resolves them on the service.
 */
export function ReviewTasksTable({ rows, caption, showStatus = false }: ReviewTasksTableProps) {
  return (
    <Table data-slot="review-tasks-table" scrollLabel={caption}>
      <TableCaption>{caption}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{t("reviewTask.attribute")}</TableHead>
          <TableHead>{t("reviewTask.reason")}</TableHead>
          <TableHead>{t("reviewTask.year")}</TableHead>
          <TableHead>{t("reviewTask.openedAt")}</TableHead>
          <TableHead>{t("reviewTask.node")}</TableHead>
          {showStatus ? <TableHead>{t("reviewTask.status")}</TableHead> : null}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id} data-task-id={row.id}>
            <TableCell className="font-medium">{row.attributeLabel}</TableCell>
            <TableCell>{row.reasonLabel}</TableCell>
            <TableCell>{row.asOfFy ?? t("reviewTask.noYear")}</TableCell>
            <TableCell>{row.openedAt}</TableCell>
            <TableCell>{row.nodeName}</TableCell>
            {showStatus ? (
              <TableCell>
                <StatusChip
                  status={row.open ? "open" : "closed"}
                  tone={row.open ? "warning" : "neutral"}
                  label={row.statusLabel}
                />
              </TableCell>
            ) : null}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
