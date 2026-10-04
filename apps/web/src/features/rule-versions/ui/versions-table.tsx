import type { Route } from "next";
import Link from "next/link";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDate, formatDateTime } from "@/shared/lib/dates";
import { RuleVersionStatusChip, SeedStatusChip } from "@/shared/ui/rule-version-status";
import type { VersionRow } from "../model/version-list";

export interface VersionsTableProps {
  rows: readonly VersionRow[];
  caption: string;
}

/**
 * Rule versions by rule key: each opens its page, with its status, whether an analyst has
 * reviewed it, its effective period, the review it needs and when it was published.
 */
export function VersionsTable({ rows, caption }: VersionsTableProps) {
  return (
    <Table data-slot="versions-table" scrollLabel={t("ruleVersions.tableRegion")}>
      <TableCaption className="text-left text-sm text-fg-muted">{caption}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{t("ruleVersions.column.version")}</TableHead>
          <TableHead>{t("ruleVersions.column.status")}</TableHead>
          <TableHead>{t("ruleVersions.column.effective")}</TableHead>
          <TableHead>{t("ruleVersions.column.review")}</TableHead>
          <TableHead>{t("ruleVersions.column.published")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow
            key={row.ruleVersionId}
            data-rule-version={row.ruleVersionId}
            data-rule={row.ruleKey}
            data-status={row.status}
          >
            <TableCell className="align-top">
              <div className="flex flex-col gap-1">
                <Link
                  href={row.href as Route}
                  className="font-mono text-sm text-primary underline-offset-2 hover:underline"
                >
                  {t("ruleVersions.versionName", { rule: row.ruleKey, version: row.version })}
                </Link>
                <span className="text-sm text-fg">{row.title}</span>
              </div>
            </TableCell>
            <TableCell className="align-top">
              <div className="flex flex-col items-start gap-1">
                <RuleVersionStatusChip status={row.status} />
                <SeedStatusChip seedStatus={row.seedStatus} />
              </div>
            </TableCell>
            <TableCell className="align-top whitespace-nowrap">
              {t("ruleVersions.period", {
                from: formatDate(row.effectiveFrom),
                to:
                  row.effectiveTo === null
                    ? t("ruleVersions.openEnded")
                    : formatDate(row.effectiveTo),
              })}
            </TableCell>
            <TableCell className="align-top">
              <ul className="flex flex-col gap-1 text-sm">
                <li>
                  {row.highImpact ? t("ruleVersions.twoApprovers") : t("ruleVersions.oneApprover")}
                </li>
                <li className="text-fg-muted">
                  {t("ruleVersions.openQuestions", { count: row.openQuestions })}
                </li>
              </ul>
            </TableCell>
            <TableCell className="align-top whitespace-nowrap text-fg-muted">
              {row.publishedAt === null
                ? t("ruleVersions.notPublished")
                : formatDateTime(row.publishedAt)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
