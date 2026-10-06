import type { Route } from "next";
import Link from "next/link";
import {
  Banner,
  Button,
  EmptyState,
  Field,
  Input,
  KeyValue,
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
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import { LOOKUP_PARAMS, type NodeLookup } from "../model/lookup";
import type { NodeReviewView } from "../model/node-review";

export interface ReviewTasksViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The page itself, without a query: the lookup form's action. */
  pageHref: string;
  lookup: NodeLookup;
  /** The node the lookup found; null before a lookup, when none was found or the read failed. */
  view: NodeReviewView | null;
  /** The lookup ran and the tenant holds no node with that id. */
  notFound: boolean;
  error?: ServiceErrorLike;
}

function formValues(lookup: NodeLookup): { tenant: string; node: string; fy: string } {
  if (lookup.kind === "ok") return { tenant: lookup.tenantId, node: lookup.nodeId, fy: lookup.fy };
  if (lookup.kind === "invalid") return lookup.values;
  return { tenant: "", node: "", fy: lookup.fy };
}

function Found({ view }: { view: NodeReviewView }) {
  const { node, snapshot } = view;
  return (
    <div className="flex flex-col gap-6" data-slot="node-review">
      <KeyValue
        data-slot="node-facts"
        items={[
          { key: "level", label: t("profileReview.fact.level"), value: node.levelLabel },
          {
            key: "key",
            label: t("profileReview.fact.key"),
            value: <span className="font-mono">{node.key}</span>,
          },
          { key: "name", label: t("profileReview.fact.name"), value: node.name },
          { key: "version", label: t("profileReview.fact.version"), value: String(node.version) },
          {
            key: "parent",
            label: t("profileReview.fact.parent"),
            value:
              node.parentHref === null ? (
                t("profileReview.noParent")
              ) : (
                <Link
                  href={node.parentHref as Route}
                  className="font-mono text-xs text-primary underline-offset-2 hover:underline"
                >
                  {node.parentId}
                </Link>
              ),
          },
          {
            key: "id",
            label: t("profileReview.fact.id"),
            value: <code className="font-mono text-xs">{node.id}</code>,
            copy: node.id,
            copyLabel: t("profileReview.copyId"),
          },
        ]}
      />
      {view.ontologyMissing ? (
        <Banner tone="warning" title={t("profileReview.ontologyMissing")} />
      ) : null}
      <section aria-labelledby="review-tasks-heading" className="flex flex-col gap-3">
        <h2 id="review-tasks-heading" className="text-lg font-semibold text-fg">
          {t("profileReview.tasksTitle")}
        </h2>
        {view.tasks.length === 0 ? (
          <EmptyState
            title={t("profileReview.noTasksTitle")}
            body={t("profileReview.noTasksBody")}
          />
        ) : (
          <Table scrollLabel={t("profileReview.tasksRegion")}>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("profileReview.tasksCaption", { count: view.tasks.length })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("profileReview.column.attribute")}</TableHead>
                <TableHead>{t("profileReview.column.reason")}</TableHead>
                <TableHead>{t("profileReview.column.year")}</TableHead>
                <TableHead>{t("profileReview.column.opened")}</TableHead>
                <TableHead>{t("profileReview.column.status")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.tasks.map((task) => (
                <TableRow key={task.id} data-task={task.id}>
                  <TableCell className="align-top text-sm">
                    <div className="flex flex-col gap-0.5">
                      <span>{task.attributeName}</span>
                      <code className="font-mono text-xs text-fg-muted">{task.attributeKey}</code>
                    </div>
                  </TableCell>
                  <TableCell className="align-top text-sm">{task.reasonLabel}</TableCell>
                  <TableCell className="align-top text-sm">
                    {task.asOfFy ?? <span className="text-fg-muted">{t("common.none")}</span>}
                  </TableCell>
                  <TableCell className="align-top text-sm">{task.openedAt}</TableCell>
                  <TableCell className="align-top">
                    <StatusChip
                      status={task.open ? "open" : "closed"}
                      tone={task.open ? "warning" : "neutral"}
                      label={task.open ? t("profileReview.open") : t("profileReview.closed")}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <p className="max-w-prose text-sm text-fg-muted">{t("profileReview.closingNote")}</p>
      </section>
      <section aria-labelledby="snapshot-heading" className="flex flex-col gap-3">
        <h2 id="snapshot-heading" className="text-lg font-semibold text-fg">
          {t("profileReview.snapshotTitle", { fy: view.fy })}
        </h2>
        <p className="max-w-prose text-sm text-fg-muted">
          {t("profileReview.snapshotFacts", {
            version: snapshot.version,
            ancestors: snapshot.lineage.length,
          })}
        </p>
        {snapshot.rows.length === 0 ? (
          <EmptyState
            title={t("profileReview.noValuesTitle")}
            body={t("profileReview.noValuesBody", { fy: view.fy })}
          />
        ) : (
          <Table scrollLabel={t("profileReview.snapshotRegion")}>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("profileReview.snapshotCaption", { count: snapshot.rows.length })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("profileReview.column.attribute")}</TableHead>
                <TableHead>{t("profileReview.column.value")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {snapshot.rows.map((row) => (
                <TableRow key={row.key} data-attribute={row.key}>
                  <TableCell className="align-top text-sm">
                    <div className="flex flex-col gap-0.5">
                      <span>{row.name}</span>
                      <code className="font-mono text-xs text-fg-muted">{row.key}</code>
                    </div>
                  </TableCell>
                  <TableCell className="align-top text-sm">{row.value}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
    </div>
  );
}

/**
 * The profile review task lookup: one node of one tenant, its open review tasks and what the
 * applicability engine evaluates for it in a year. The profile routes act for the tenant named in
 * x-tenant-id, so the screen is a lookup by tenant id and node id (a GET form; ids are not
 * personal data). It reads only: a task closes when the attribute is answered on the business's
 * own pages, and no route lists a tenant's tasks.
 */
export function ReviewTasksView({
  title,
  crumbs,
  pageHref,
  lookup,
  view,
  notFound,
  error,
}: ReviewTasksViewProps) {
  const values = formValues(lookup);
  const errors = lookup.kind === "invalid" ? lookup.errors : {};
  return (
    <div data-slot="profile-review-tasks" className="flex max-w-5xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("profileReview.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <form
        method="get"
        action={pageHref}
        aria-label={t("profileReview.formLabel")}
        data-slot="node-lookup"
        noValidate
        className="grid max-w-4xl items-end gap-3 sm:grid-cols-[2fr_2fr_1fr_auto]"
      >
        <Field id="lookup-tenant" label={t("profileReview.tenant")} error={errors.tenant} required>
          <Input
            name={LOOKUP_PARAMS.tenant}
            defaultValue={values.tenant}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Field id="lookup-node" label={t("profileReview.node")} error={errors.node} required>
          <Input
            name={LOOKUP_PARAMS.node}
            defaultValue={values.node}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Field
          id="lookup-fy"
          label={t("profileReview.fy")}
          description={t("profileReview.fyHelp")}
          error={errors.fy}
        >
          <Input
            name={LOOKUP_PARAMS.fy}
            defaultValue={values.fy}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Button type="submit" variant="secondary">
          {t("profileReview.submit")}
        </Button>
      </form>
      {lookup.kind === "empty" ? (
        <p className="max-w-prose text-sm text-fg-muted">{t("profileReview.help")}</p>
      ) : null}
      {error !== undefined ? <ServiceError error={error} /> : null}
      {notFound ? (
        <EmptyState
          title={t("profileReview.notFoundTitle")}
          body={t("profileReview.notFoundBody")}
        />
      ) : null}
      {view === null ? null : <Found view={view} />}
    </div>
  );
}
