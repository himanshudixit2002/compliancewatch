"use client";

import type { Route } from "next";
import Link from "next/link";
import { useId, useState } from "react";
import {
  CopyButton,
  Field,
  Input,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { filterRules, type RuleRow } from "./rules-shared";

export interface RulesTableProps {
  rows: readonly RuleRow[];
}

/**
 * The rules with a filter typed over them: each word must appear in the key, the title or the
 * regulator. The count of rules shown is announced politely as the filter changes; nothing is
 * read again, since the page already holds every rule.
 */
export function RulesTable({ rows }: RulesTableProps) {
  const id = useId();
  const [query, setQuery] = useState("");
  const shown = filterRules(rows, query);
  return (
    <div className="flex flex-col gap-4" data-slot="rules-table">
      <Field
        id={`${id}-filter`}
        label={t("rules.filter")}
        description={t("rules.filterHelp")}
        className="max-w-md"
      >
        <Input
          type="search"
          value={query}
          autoComplete="off"
          onChange={(event) => setQuery(event.target.value)}
        />
      </Field>
      <p className="text-sm text-fg-muted" aria-live="polite" data-slot="rules-count">
        {t("rules.shown", { shown: shown.length, total: rows.length })}
      </p>
      {shown.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("rules.noMatch")}</p>
      ) : (
        <Table scrollLabel={t("rules.tableRegion")}>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("rules.caption", { count: shown.length })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("rules.column.rule")}</TableHead>
              <TableHead>{t("rules.column.title")}</TableHead>
              <TableHead>{t("rules.column.regulator")}</TableHead>
              <TableHead>{t("rules.column.id")}</TableHead>
              <TableHead>{t("rules.column.versions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((row) => (
              <TableRow key={row.ruleKey} data-rule={row.ruleKey}>
                <TableCell className="align-top">
                  <code className="font-mono text-sm text-fg">{row.ruleKey}</code>
                </TableCell>
                <TableCell className="align-top text-sm">{row.title}</TableCell>
                <TableCell className="align-top text-sm">{row.regulator}</TableCell>
                <TableCell className="align-top">
                  <span className="flex items-center gap-1">
                    <code className="font-mono text-xs text-fg-muted">{row.ruleId}</code>
                    <CopyButton
                      value={row.ruleId}
                      label={t("rules.copyId", { rule: row.ruleKey })}
                      size="sm"
                    />
                  </span>
                </TableCell>
                <TableCell className="align-top text-sm">
                  <Link
                    href={row.versionsHref as Route}
                    className="text-primary underline-offset-2 hover:underline"
                  >
                    {t("rules.versions", { rule: row.ruleKey })}
                  </Link>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
