import type { Route } from "next";
import Link from "next/link";
import {
  Button,
  EmptyState,
  Field,
  PageHeader,
  Select,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { KeysetPager } from "@/shared/ui/keyset-pager";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import {
  QUEUE_PARAMS,
  entityTypeLabel,
  typeOptions,
  type QueueFilter,
  type QueueRead,
  type QueueView,
} from "../model/queue";

export interface EntityQueueViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The queue itself, without a query: the filter form's action. */
  pageHref: string;
  read: QueueRead;
  /** The page the filter found; null when the filter was refused or the read failed. */
  view: QueueView | null;
  error?: ServiceErrorLike;
}

/**
 * Why a page holds no group: a later page past the queue's end (the first page is offered below),
 * the type the form names, or the queue itself.
 */
function emptyText(filter: QueueFilter): { title: string; body: string } {
  const type = filter.entityType === null ? null : entityTypeLabel(filter.entityType);
  if (filter.after !== null) {
    return {
      title:
        type === null
          ? t("entityReview.empty.laterTitle")
          : t("entityReview.empty.laterTypeTitle", { type }),
      body: t("entityReview.empty.laterBody"),
    };
  }
  if (type !== null) {
    return {
      title: t("entityReview.empty.typeTitle", { type }),
      body: t("entityReview.empty.typeBody", { type }),
    };
  }
  return { title: t("entityReview.empty.title"), body: t("entityReview.empty.body") };
}

/**
 * The entity review queue: the mentions alignment could not settle on its own, grouped by entity
 * type and proposed name, each group with how many mentions are open and the first of them with
 * why it is open. A group opens on its own page, where an analyst decides it. The type filter is
 * a GET form and the pages are links, so a page of the queue can be shared.
 */
export function EntityQueueView({
  title,
  crumbs,
  pageHref,
  read,
  view,
  error,
}: EntityQueueViewProps) {
  const typeValue = read.kind === "invalid" ? read.value : (read.filter.entityType ?? "");
  return (
    <div data-slot="entity-queue" className="flex max-w-6xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("entityReview.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <form
        method="get"
        action={pageHref}
        aria-label={t("entityReview.filterLabel")}
        data-slot="entity-filter"
        noValidate
        className="flex flex-wrap items-end gap-3"
      >
        <Field
          id="entity-queue-type"
          label={t("entityReview.typeField")}
          error={read.kind === "invalid" ? t("entityReview.typeInvalid") : undefined}
          className="w-full max-w-xs"
        >
          <Select name={QUEUE_PARAMS.type} defaultValue={typeValue} options={typeOptions()} />
        </Field>
        <Button type="submit" variant="secondary">
          {t("entityReview.filterSubmit")}
        </Button>
      </form>
      {error !== undefined ? <ServiceError error={error} /> : null}
      {view === null ? null : view.rows.length === 0 ? (
        <>
          <EmptyState {...emptyText(view.filter)} />
          <KeysetPager
            nextHref={null}
            firstHref={view.firstHref}
            label={t("entityReview.pager")}
            nextLabel={t("entityReview.nextPage")}
            firstLabel={t("entityReview.firstPage")}
          />
        </>
      ) : (
        <>
          <Table scrollLabel={t("entityReview.tableRegion")}>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("entityReview.caption", {
                count: view.rows.length,
                mentions: view.mentionsOnPage,
              })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("entityReview.column.group")}</TableHead>
                <TableHead>{t("entityReview.column.type")}</TableHead>
                <TableHead>{t("entityReview.column.open")}</TableHead>
                <TableHead>{t("entityReview.column.example")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.rows.map((row) => (
                <TableRow
                  key={row.key}
                  data-group={`${row.entityType}:${row.name}`}
                  data-slot="entity-group-row"
                >
                  <TableCell className="align-top">
                    <Link
                      href={row.href as Route}
                      className="font-medium text-primary underline-offset-2 hover:underline"
                    >
                      {row.nameLabel}
                    </Link>
                  </TableCell>
                  <TableCell className="align-top text-sm">{row.typeLabel}</TableCell>
                  <TableCell className="align-top text-sm">{row.openCount}</TableCell>
                  <TableCell className="align-top text-sm">
                    {row.example === null ? (
                      <span className="text-fg-muted">{t("common.none")}</span>
                    ) : (
                      <div className="flex flex-col gap-1">
                        <span className="whitespace-pre-wrap text-fg">{row.example.text}</span>
                        <span className="text-xs text-fg-muted">{row.example.reasonLabel}</span>
                        <Link
                          href={row.example.documentHref as Route}
                          className="text-xs text-primary underline-offset-2 hover:underline"
                        >
                          {t("entityReview.items.showInDocument")}
                        </Link>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <KeysetPager
            nextHref={view.nextHref}
            firstHref={view.firstHref}
            label={t("entityReview.pager")}
            nextLabel={t("entityReview.nextPage")}
            firstLabel={t("entityReview.firstPage")}
          />
        </>
      )}
    </div>
  );
}
