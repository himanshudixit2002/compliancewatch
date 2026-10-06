import type { Route } from "next";
import Link from "next/link";
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
import type { FanOutRow } from "../model/fan-outs";

export interface FanOutsTableProps {
  rows: readonly FanOutRow[];
}

/**
 * The runs, newest first: the version (which opens its run), the status with its last change,
 * how many businesses of the level it decided and how many it applies to, its flips against the
 * version it supersedes, and when it started and last moved.
 */
export function FanOutsTable({ rows }: FanOutsTableProps) {
  return (
    <Table data-slot="fan-outs-table" scrollLabel={t("fanOuts.tableRegion")}>
      <TableCaption className="text-left text-sm text-fg-muted">
        {t("fanOuts.caption", { count: rows.length })}
      </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("fanOuts.column.version")}</TableHead>
          <TableHead scope="col">{t("fanOuts.column.status")}</TableHead>
          <TableHead scope="col">{t("fanOuts.column.progress")}</TableHead>
          <TableHead scope="col">{t("fanOuts.column.flips")}</TableHead>
          <TableHead scope="col">{t("fanOuts.column.when")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow
            key={row.ruleVersionId}
            data-fan-out={row.ruleVersionId}
            data-status={row.status}
          >
            <TableCell className="align-top whitespace-normal">
              <div className="flex flex-col gap-1">
                <Link
                  href={row.href as Route}
                  className="font-medium text-primary underline-offset-2 hover:underline"
                >
                  {row.name}
                </Link>
                {row.title === null ? null : (
                  <span className="text-xs text-fg-muted">{row.title}</span>
                )}
                <span className="text-xs text-fg-muted">{row.level}</span>
              </div>
            </TableCell>
            <TableCell className="align-top whitespace-normal">
              <StatusChip status={row.status} tone={row.statusTone} label={row.statusLabel} />
              {row.lastChange === null ? null : (
                <span className="mt-1 block text-xs text-fg-muted">{row.lastChange}</span>
              )}
            </TableCell>
            <TableCell className="align-top whitespace-normal">
              <span className="block">{row.progress}</span>
              <span className="block text-xs text-fg-muted">
                {t("fanOuts.appliesTo", { count: row.applies })}
              </span>
            </TableCell>
            <TableCell className="align-top whitespace-normal">{row.flips}</TableCell>
            <TableCell className="align-top whitespace-normal">
              <time dateTime={row.startedIso} className="block">
                {t("fanOuts.startedAt", { when: row.started })}
              </time>
              <span className="block text-xs text-fg-muted">{row.lastMoved}</span>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
