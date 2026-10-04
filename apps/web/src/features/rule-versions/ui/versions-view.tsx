import type { Route } from "next";
import Link from "next/link";
import { Button, DateField, EmptyState, Field, PageHeader, Select, cn } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import {
  LIST_PARAMS,
  listHref,
  type ListFilterRead,
  type VersionListFilter,
} from "../model/list-filter";
import {
  statusChipLabel,
  statusChips,
  type RuleOption,
  type VersionListView,
} from "../model/version-list";
import { ListPager } from "./list-pager";
import { VersionsTable } from "./versions-table";

export interface VersionsViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The list itself, without a query: the chips' and the form's base. */
  pageHref: string;
  read: ListFilterRead;
  /** The page the filter found; null when the filter was refused or the read failed. */
  view: VersionListView | null;
  error?: ServiceErrorLike;
}

function modeSentence(filter: VersionListFilter): string {
  const rule = filter.ruleKey === null ? t("ruleVersions.everyRuleLower") : filter.ruleKey;
  return filter.status === "in_force"
    ? t("ruleVersions.mode.inForce", { date: formatDate(filter.asOf), rule })
    : filter.status === "all"
      ? t("ruleVersions.mode.all", { rule })
      : t("ruleVersions.mode.status", { status: statusChipLabel(filter.status), rule });
}

function Empty({ filter, pageHref }: { filter: VersionListFilter; pageHref: string }) {
  if (filter.status === "in_force") {
    return (
      <EmptyState
        title={t("ruleVersions.empty.inForceTitle", { date: formatDate(filter.asOf) })}
        body={t("ruleVersions.empty.inForceBody")}
        action={
          <Link
            href={listHref(pageHref, { ...filter, status: "draft" }) as Route}
            className="text-sm text-primary underline-offset-2 hover:underline"
          >
            {t("ruleVersions.empty.seeDrafts")}
          </Link>
        }
      />
    );
  }
  return (
    <EmptyState
      title={t("ruleVersions.empty.statusTitle", { status: statusChipLabel(filter.status) })}
      body={t("ruleVersions.empty.statusBody")}
    />
  );
}

/**
 * The rule versions, by rule key: in force on a date (the rulebook's as-of read: published or
 * superseded versions whose period covers the date), or in one status of the review flow, drafts
 * included, from each rule's versions. The chips and the form are links and GET requests, so a
 * filtered list can be shared; each page continues after the last rule key, as the rulebook does.
 */
export function VersionsView({ title, crumbs, pageHref, read, view, error }: VersionsViewProps) {
  const { filter, invalid } = read;
  const chips = statusChips(pageHref, filter);
  const ruleOptions: readonly RuleOption[] =
    view?.rules ??
    (filter.ruleKey === null ? [] : [{ value: filter.ruleKey, label: filter.ruleKey }]);
  return (
    <div data-slot="rule-versions" className="flex max-w-6xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("ruleVersions.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <nav aria-label={t("ruleVersions.chipsLabel")} data-slot="status-chips">
        <ul className="flex flex-wrap gap-2">
          {chips.map((chip) => (
            <li key={chip.status}>
              <Link
                href={chip.href as Route}
                aria-current={chip.current ? "true" : undefined}
                data-status={chip.status}
                className={cn(
                  "inline-flex items-center rounded-full border px-3 py-1 text-sm font-medium underline-offset-2 hover:underline",
                  chip.current
                    ? "border-primary bg-primary text-primary-fg"
                    : "border-line-strong bg-surface text-fg",
                )}
              >
                {chip.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <form
        method="get"
        action={pageHref}
        aria-label={t("ruleVersions.filterLabel")}
        data-slot="version-filter"
        noValidate
        className="flex flex-wrap items-end gap-3"
      >
        {filter.status === "in_force" ? (
          <DateField
            id="versions-as-of"
            name={LIST_PARAMS.asOf}
            label={t("ruleVersions.asOf")}
            description={t("ruleVersions.asOfHelp")}
            defaultValue={invalid.asOf ?? filter.asOf}
            error={invalid.asOf === undefined ? undefined : t("ruleVersions.asOfInvalid")}
          />
        ) : (
          <input type="hidden" name={LIST_PARAMS.status} value={filter.status} />
        )}
        <Field
          id="versions-rule"
          label={t("ruleVersions.rule")}
          error={invalid.rule === undefined ? undefined : t("ruleVersions.ruleInvalid")}
          className="w-full max-w-md"
        >
          <Select
            name={LIST_PARAMS.rule}
            defaultValue={filter.ruleKey ?? ""}
            options={[{ value: "", label: t("ruleVersions.everyRule") }, ...ruleOptions]}
          />
        </Field>
        <Button type="submit" variant="secondary">
          {t("ruleVersions.apply")}
        </Button>
      </form>
      <p className="max-w-prose text-sm text-fg-muted" data-slot="list-mode">
        {modeSentence(filter)}
      </p>
      {error !== undefined ? <ServiceError error={error} /> : null}
      {Object.keys(invalid).length > 0 ? (
        <p className="text-sm text-fg-muted">{t("ruleVersions.fixFilter")}</p>
      ) : null}
      {view === null ? null : view.rows.length === 0 ? (
        <Empty filter={filter} pageHref={pageHref} />
      ) : (
        <VersionsTable
          rows={view.rows}
          caption={t("ruleVersions.caption", { count: view.rows.length })}
        />
      )}
      {view === null ? null : (
        <ListPager
          nextHref={view.nextHref}
          firstHref={view.firstHref}
          label={t("ruleVersions.pager")}
        />
      )}
    </div>
  );
}
