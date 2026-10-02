import type { Route } from "next";
import Link from "next/link";
import {
  Button,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Select,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  ENGAGEMENT_STATUSES,
  engagementTone,
  filterClients,
  isFiltered,
  summarizeClients,
  type CaClient,
  type ClientFilter,
  type EngagementStatus,
} from "../model/clients";

export interface CaDashboardViewProps {
  clients: readonly CaClient[];
  filter: ClientFilter;
  /** The page itself, without a query: the filter form submits to it with GET. */
  action: string;
  /** The page without any filter. */
  clearHref: Route;
  clientHref: (clientId: string) => Route;
}

const STATUS_LABEL: Readonly<Record<EngagementStatus, MessageKey>> = {
  active: "caDashboard.status.active",
  pending: "caDashboard.status.pending",
  inactive: "caDashboard.status.inactive",
};

function FilterForm({ filter, action }: { filter: ClientFilter; action: string }) {
  return (
    <form
      method="get"
      action={action}
      role="search"
      aria-label={t("caDashboard.filterLabel")}
      className="flex flex-wrap items-end gap-3"
    >
      <Field id="ca-client-search" label={t("caDashboard.search")} className="min-w-56 flex-1">
        <Input name="q" type="search" defaultValue={filter.query} />
      </Field>
      <Field id="ca-client-status" label={t("caDashboard.statusFilter")} className="w-48">
        <Select
          name="status"
          defaultValue={filter.status}
          options={[
            { value: "all", label: t("caDashboard.status.all") },
            ...ENGAGEMENT_STATUSES.map((status) => ({
              value: status,
              label: t(STATUS_LABEL[status]),
            })),
          ]}
        />
      </Field>
      <Button type="submit" variant="secondary">
        {t("caDashboard.apply")}
      </Button>
    </form>
  );
}

function ClientsTable({
  clients,
  clientHref,
}: {
  clients: readonly CaClient[];
  clientHref: CaDashboardViewProps["clientHref"];
}) {
  return (
    <Table>
      <TableCaption className="sr-only">{t("caDashboard.tableCaption")}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{t("caDashboard.column.client")}</TableHead>
          <TableHead>{t("caDashboard.column.status")}</TableHead>
          <TableHead>{t("caDashboard.column.score")}</TableHead>
          <TableHead>{t("caDashboard.column.due")}</TableHead>
          <TableHead>{t("caDashboard.column.overdue")}</TableHead>
          <TableHead>{t("caDashboard.column.assignedTo")}</TableHead>
          <TableHead>{t("caDashboard.column.updated")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {clients.map((client) => (
          <TableRow key={client.id} data-client={client.id}>
            <TableCell>
              <Link
                href={clientHref(client.id)}
                className="font-medium text-primary hover:underline"
              >
                {client.name}
              </Link>
            </TableCell>
            <TableCell>
              <StatusChip
                status={client.engagementStatus}
                tone={engagementTone(client.engagementStatus)}
                label={t(STATUS_LABEL[client.engagementStatus])}
              />
            </TableCell>
            <TableCell>
              {client.complianceScore === null
                ? t("common.none")
                : t("caDashboard.percent", { value: client.complianceScore })}
            </TableCell>
            <TableCell>{client.obligationsDue}</TableCell>
            <TableCell
              className={client.obligationsOverdue > 0 ? "font-semibold text-danger" : undefined}
            >
              {client.obligationsOverdue}
            </TableCell>
            <TableCell className="text-fg-muted">
              {client.assignedTo ?? t("caDashboard.unassigned")}
            </TableCell>
            <TableCell className="text-fg-muted">{formatDate(client.updatedAt)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * A CA firm's clients: totals across them, then the list filtered by name and engagement status.
 * The filter is a GET form, so it lives in the URL and works without JavaScript.
 */
export function CaDashboardView({
  clients,
  filter,
  action,
  clearHref,
  clientHref,
}: CaDashboardViewProps) {
  const summary = summarizeClients(clients);
  const shown = filterClients(clients, filter);
  return (
    <div data-slot="ca-dashboard" className="flex flex-col gap-6">
      <PageHeader title={t("caDashboard.title")} description={t("caDashboard.intro")} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard label={t("caDashboard.totalClients")} value={summary.total} />
        <StatCard label={t("caDashboard.activeClients")} value={summary.active} tone="success" />
        <StatCard label={t("caDashboard.obligationsDue")} value={summary.due} tone="warning" />
        <StatCard
          label={t("caDashboard.obligationsOverdue")}
          value={summary.overdue}
          tone={summary.overdue > 0 ? "danger" : "neutral"}
        />
        <StatCard
          label={t("caDashboard.averageScore")}
          value={
            summary.averageScore === null
              ? t("common.none")
              : t("caDashboard.percent", { value: summary.averageScore })
          }
          tone="info"
        />
      </div>
      {clients.length === 0 ? (
        <EmptyState title={t("caDashboard.emptyTitle")} body={t("caDashboard.emptyBody")} />
      ) : (
        <>
          <FilterForm filter={filter} action={action} />
          {shown.length === 0 ? (
            <EmptyState
              title={t("caDashboard.noMatchTitle")}
              body={t("caDashboard.noMatchBody")}
              action={
                <Button asChild variant="secondary">
                  <Link href={clearHref}>{t("caDashboard.clear")}</Link>
                </Button>
              }
            />
          ) : (
            <>
              <p className="text-sm text-fg-muted" aria-live="polite">
                {isFiltered(filter)
                  ? t("caDashboard.showingFiltered", { shown: shown.length, total: clients.length })
                  : t("caDashboard.showingAll", { total: clients.length })}
              </p>
              <ClientsTable clients={shown} clientHref={clientHref} />
            </>
          )}
        </>
      )}
    </div>
  );
}
