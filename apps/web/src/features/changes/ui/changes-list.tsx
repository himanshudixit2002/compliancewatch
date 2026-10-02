"use client";

import Link from "next/link";
import { useId, useState } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  Select,
  type SelectOption,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ALL, NO_CHANGE_FILTERS, filterChanges, type ChangeRow } from "./change-filters";

export interface ChangesListProps {
  rows: readonly ChangeRow[];
  applicabilityOptions: readonly SelectOption[];
  reviewOptions: readonly SelectOption[];
}

/**
 * The changes as cards, narrowed in the browser by a search over title and regulator and by
 * applicability and review status. A status line says how many of the changes are shown.
 */
export function ChangesList({ rows, applicabilityOptions, reviewOptions }: ChangesListProps) {
  const id = useId();
  const [filters, setFilters] = useState(NO_CHANGE_FILTERS);
  const shown = filterChanges(rows, filters);

  return (
    <div data-slot="changes-list" className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-[1fr_12rem_12rem]">
        <Field id={`${id}-search`} label={t("changes.filter.search")}>
          <Input
            type="search"
            value={filters.search}
            onChange={(event) => setFilters({ ...filters, search: event.target.value })}
          />
        </Field>
        <Field id={`${id}-applicability`} label={t("changes.filter.applicability")}>
          <Select
            value={filters.applicability}
            onChange={(event) => setFilters({ ...filters, applicability: event.target.value })}
            options={[
              { value: ALL, label: t("changes.filter.allApplicability") },
              ...applicabilityOptions,
            ]}
          />
        </Field>
        <Field id={`${id}-review`} label={t("changes.filter.review")}>
          <Select
            value={filters.reviewStatus}
            onChange={(event) => setFilters({ ...filters, reviewStatus: event.target.value })}
            options={[{ value: ALL, label: t("changes.filter.allReview") }, ...reviewOptions]}
          />
        </Field>
      </div>
      <p role="status" className="text-sm text-fg-muted">
        {t("changes.shown", { shown: shown.length, total: rows.length })}
      </p>
      {shown.length === 0 ? (
        <EmptyState title={t("changes.noMatch.title")} body={t("changes.noMatch.body")} />
      ) : (
        <ul className="flex flex-col gap-3">
          {shown.map((row) => (
            <li key={row.id} data-change={row.id}>
              <Card className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex min-w-0 flex-col gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="font-semibold text-fg">{row.title}</h2>
                    <Badge tone={row.reviewTone}>{row.reviewLabel}</Badge>
                    <Badge tone={row.applicabilityTone}>{row.applicabilityLabel}</Badge>
                  </div>
                  <p className="max-w-2xl text-sm text-fg-muted">{row.summary}</p>
                  <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-muted">
                    {row.facts.map((fact) => (
                      <li key={fact}>{fact}</li>
                    ))}
                  </ul>
                  {row.categories.length === 0 ? null : (
                    <ul aria-label={t("changes.categories")} className="flex flex-wrap gap-1">
                      {row.categories.map((category) => (
                        <li key={category}>
                          <Badge tone="neutral">{category}</Badge>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <Button asChild variant="secondary" size="sm">
                  <Link href={row.href}>
                    {t("changes.open")}
                    <span className="sr-only"> {row.title}</span>
                  </Link>
                </Button>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
