import type { Route } from "next";
import Link from "next/link";
import {
  Banner,
  Button,
  EmptyState,
  Field,
  Input,
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
import { formatDate } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { RuleVersionStatusChip } from "@/shared/ui/rule-version-status";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import { GRAPH_PARAMS, type GraphRead } from "../model/graph-form";
import type { GraphNode, GraphView as GraphViewModel } from "../model/graph";
import { GraphSvg } from "./graph-svg";

export interface GraphViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The page itself, without a query: the form's action. */
  pageHref: string;
  read: GraphRead;
  graph: GraphViewModel | null;
  /** A start version the rulebook does not hold, answered on the form's field. */
  unknownVersion?: boolean;
  error?: ServiceErrorLike;
}

function values(read: GraphRead): { version: string; depth: string; scope: string } {
  if (read.kind === "ok") {
    return {
      version: read.ruleVersionId,
      depth: String(read.depth),
      scope: read.publishedOnly ? "published" : "all",
    };
  }
  if (read.kind === "invalid") return read.values;
  return { version: "", depth: "1", scope: "all" };
}

function NodeCell({ node }: { node: GraphNode | undefined }) {
  if (node === undefined) return <span className="text-fg-muted">-</span>;
  return (
    <span className="flex flex-wrap items-center gap-2">
      {node.href === null ? (
        <span>{node.label}</span>
      ) : (
        <Link href={node.href as Route} className="text-primary underline-offset-2 hover:underline">
          {node.label}
        </Link>
      )}
      {node.status === null ? null : <RuleVersionStatusChip status={node.status} />}
      {node.start ? <span className="text-xs text-fg-muted">{t("graph.start")}</span> : null}
    </span>
  );
}

/**
 * The relations graph around a rule version: a GET form (the version, one or two relations
 * away, every relation or only those of published versions), the graph drawn as an inline SVG,
 * and the same relations as a table, which is what assistive technology reads.
 */
export function GraphView({
  title,
  crumbs,
  pageHref,
  read,
  graph,
  unknownVersion = false,
  error,
}: GraphViewProps) {
  const current = values(read);
  const versionError =
    read.kind === "invalid"
      ? read.errors.version
      : unknownVersion
        ? t("graph.form.versionUnknown")
        : undefined;
  const nodes = new Map((graph?.nodes ?? []).map((node) => [node.key, node]));
  return (
    <div data-slot="relations-graph" className="flex max-w-6xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("graph.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <form
        method="get"
        action={pageHref}
        aria-label={t("graph.form.label")}
        data-slot="graph-form"
        noValidate
        className="grid max-w-4xl items-end gap-3 sm:grid-cols-[1fr_10rem_14rem_auto]"
      >
        <Field
          id="graph-version"
          label={t("graph.form.version")}
          description={t("graph.form.versionHelp")}
          error={versionError}
          required
        >
          <Input
            name={GRAPH_PARAMS.version}
            defaultValue={current.version}
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
          />
        </Field>
        <Field id="graph-depth" label={t("graph.form.depth")}>
          <Select
            name={GRAPH_PARAMS.depth}
            defaultValue={current.depth}
            options={[
              { value: "1", label: t("graph.form.depthOne") },
              { value: "2", label: t("graph.form.depthTwo") },
            ]}
          />
        </Field>
        <Field id="graph-scope" label={t("graph.form.scope")}>
          <Select
            name={GRAPH_PARAMS.scope}
            defaultValue={current.scope}
            options={[
              { value: "all", label: t("graph.form.scopeAll") },
              { value: "published", label: t("graph.form.scopePublished") },
            ]}
          />
        </Field>
        <Button type="submit" variant="secondary">
          {t("graph.form.submit")}
        </Button>
      </form>
      {error !== undefined ? <ServiceError error={error} /> : null}
      {graph === null ? (
        read.kind === "empty" ? (
          <EmptyState title={t("graph.emptyTitle")} body={t("graph.emptyBody")} />
        ) : null
      ) : (
        <section aria-labelledby="graph-heading" className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h2 id="graph-heading" className="text-lg font-semibold text-fg">
              {t("graph.heading", {
                version: `${graph.start.ruleKey} v${graph.start.version}`,
                title: graph.start.title,
              })}
            </h2>
            <p className="text-sm text-fg-muted" data-slot="graph-summary">
              {t("graph.summary", {
                nodes: graph.nodes.length,
                relations: graph.edges.length,
                depth: graph.depth,
              })}{" "}
              {graph.publishedOnly ? t("graph.scopePublished") : t("graph.scopeAll")}
            </p>
          </div>
          {graph.truncated ? (
            <Banner tone="warning" title={t("graph.truncatedTitle")}>
              {t("graph.truncatedBody")}
            </Banner>
          ) : null}
          <GraphSvg layout={graph.layout} />
          {graph.edges.length === 0 ? (
            <EmptyState
              heading="h3"
              title={t("graph.noRelationsTitle")}
              body={
                graph.publishedOnly ? t("graph.noRelationsPublished") : t("graph.noRelationsBody")
              }
            />
          ) : (
            <Table data-slot="graph-table" scrollLabel={t("graph.tableRegion")}>
              <TableCaption className="text-left text-sm text-fg-muted">
                {t("graph.caption", { count: graph.edges.length })}
              </TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("relations.column.from")}</TableHead>
                  <TableHead>{t("relations.column.relation")}</TableHead>
                  <TableHead>{t("relations.column.to")}</TableHead>
                  <TableHead>{t("relations.column.evidence")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {graph.edges.map((edge) => (
                  <TableRow key={edge.relationId} data-relation={edge.relation}>
                    <TableCell className="align-top">
                      <NodeCell node={nodes.get(edge.from)} />
                    </TableCell>
                    <TableCell className="align-top">
                      {humanise(edge.relation)}
                      {edge.newDueOn === null && edge.periodLabel === null ? null : (
                        <span className="block text-xs text-fg-muted">
                          {t("relations.deadline", {
                            period: edge.periodLabel ?? t("relations.noPeriod"),
                            due:
                              edge.newDueOn === null
                                ? t("relations.noDate")
                                : formatDate(edge.newDueOn),
                          })}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="align-top">
                      <NodeCell node={nodes.get(edge.to)} />
                    </TableCell>
                    <TableCell className="align-top">
                      <Link
                        href={edge.evidenceHref as Route}
                        className="text-primary underline-offset-2 hover:underline"
                      >
                        {t("relations.evidence", { ref: edge.evidenceClauseRef })}
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </section>
      )}
    </div>
  );
}
