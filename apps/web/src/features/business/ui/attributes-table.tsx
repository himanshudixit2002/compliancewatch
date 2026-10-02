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
import type { ValueState } from "@/entities/business/types";
import { t } from "@/shared/i18n";
import { ValueStateChip } from "./value-state-chip";

/** One stored value as the table shows it (the business model's attribute rows, structurally). */
export interface AttributesTableRow {
  id: string;
  label: string;
  definition: string;
  state: ValueState;
  valueText: string;
  asOfFy: string | null;
  sourceLabel: string;
  updatedAt: string | null;
  /** Own rows: where "Change" leads, or null. */
  editHref?: string | null;
  /** Inherited rows: the node the value is stored on. */
  fromName?: string;
}

export interface AttributesTableProps {
  rows: readonly AttributesTableRow[];
  caption: string;
  /** "own" adds the change column when any row can change; "inherited" adds the source node. */
  variant: "own" | "inherited";
}

/**
 * A node's values: the attribute (its definition in a disclosure), the answer as a state chip
 * and the value worded by the ontology, the year of a per-year value, where it came from and when
 * it changed in IST; on the node's own values a link to change one, on inherited values the node
 * that holds it.
 */
export function AttributesTable({ rows, caption, variant }: AttributesTableProps) {
  const changeColumn = variant === "own" && rows.some((row) => row.editHref);
  return (
    <Table data-slot={`attributes-table-${variant}`} scrollLabel={caption}>
      <TableCaption>{caption}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{t("attributes.column.attribute")}</TableHead>
          <TableHead>{t("attributes.column.answer")}</TableHead>
          <TableHead>{t("attributes.column.year")}</TableHead>
          {variant === "inherited" ? <TableHead>{t("attributes.column.from")}</TableHead> : null}
          <TableHead>{t("attributes.column.source")}</TableHead>
          <TableHead>{t("attributes.column.updated")}</TableHead>
          {changeColumn ? (
            <TableHead>
              <span className="sr-only">{t("attributes.column.change")}</span>
            </TableHead>
          ) : null}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id} data-attribute={row.id}>
            <TableCell className="align-top">
              {row.definition === "" ? (
                <span className="font-medium">{row.label}</span>
              ) : (
                <details>
                  <summary className="cursor-pointer font-medium">{row.label}</summary>
                  <p className="mt-1 max-w-sm text-xs text-fg-muted">{row.definition}</p>
                </details>
              )}
            </TableCell>
            <TableCell className="align-top">
              <div className="flex flex-col items-start gap-1">
                <ValueStateChip state={row.state} />
                {row.state === "known" ? <span>{row.valueText}</span> : null}
              </div>
            </TableCell>
            <TableCell className="align-top">{row.asOfFy ?? t("reviewTask.noYear")}</TableCell>
            {variant === "inherited" ? (
              <TableCell className="align-top">{row.fromName}</TableCell>
            ) : null}
            <TableCell className="align-top">{row.sourceLabel}</TableCell>
            <TableCell className="align-top">{row.updatedAt ?? t("common.unknown")}</TableCell>
            {changeColumn ? (
              <TableCell className="align-top">
                {row.editHref ? (
                  <Link href={row.editHref as Route} className="text-primary underline">
                    {t("attributes.change")} <span className="sr-only">{row.label}</span>
                  </Link>
                ) : null}
              </TableCell>
            ) : null}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
