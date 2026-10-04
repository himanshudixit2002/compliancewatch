import {
  Badge,
  EmptyState,
  ErrorState,
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
import { formatDate } from "@/shared/lib/dates";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { StatCard } from "@/shared/ui/stat-card";
import { EXPIRY_WARNING_DAYS } from "../model/flags";
import type { FlagConsoleView, FlagRow } from "../model/flags";

export interface FlagsViewProps {
  title: string;
  crumbs: readonly Crumb[];
  view: FlagConsoleView;
}

function Code({ children }: { children: string }) {
  return <code className="font-mono text-xs text-fg">{children}</code>;
}

function DefaultCell({ row }: { row: FlagRow }) {
  if (row.type === "bool") return <span className="text-fg">{t("flags.default.off")}</span>;
  return (
    <div className="flex flex-col gap-1">
      <Code>{String(row.defaultValue)}</Code>
      <span className="text-xs text-fg-muted">
        {t("flags.values", { values: row.values.join(", ") })}
      </span>
    </div>
  );
}

function ValueCell({ row }: { row: FlagRow }) {
  switch (row.value.kind) {
    case "on":
      return <StatusChip status="on" tone="success" label={t("flags.value.on")} />;
    case "off":
      return <StatusChip status="off" tone="neutral" label={t("flags.value.off")} />;
    case "unknown":
      return <StatusChip status="unknown" tone="warning" label={t("flags.value.unknown")} />;
    case "elsewhere":
      return (
        <span className="text-xs text-fg-muted">
          {t("flags.value.elsewhere", { services: row.value.services.join(", ") })}
        </span>
      );
  }
}

function ExpiryCell({ row }: { row: FlagRow }) {
  const { state, days } = row.expiry;
  return (
    <div className="flex flex-col items-start gap-1">
      <span className={state === "later" ? "text-fg-muted" : "text-fg"}>
        {formatDate(row.expires)}
      </span>
      {state === "expired" ? <Badge tone="danger">{t("flags.expired")}</Badge> : null}
      {state === "soon" ? (
        <Badge tone="warning">
          {days === 0 ? t("flags.expiresToday") : t("flags.expiresIn", { days })}
        </Badge>
      ) : null}
    </div>
  );
}

function FlagTableRow({ row }: { row: FlagRow }) {
  return (
    <TableRow data-flag={row.name} data-value={row.value.kind}>
      <TableCell className="align-top">
        <div className="flex flex-col gap-1">
          <Code>{row.name}</Code>
          <span className="text-xs text-fg-muted">
            {row.type === "bool" ? t("flags.type.bool") : t("flags.type.string")}
          </span>
          {row.env === null ? null : (
            <span className="text-xs text-fg-muted">{t("flags.variable", { env: row.env })}</span>
          )}
          {row.targeting === "tenant" ? (
            <span className="text-xs text-fg-muted">
              {row.tenantsEnv === null
                ? t("flags.tenants")
                : t("flags.tenantsList", { env: row.tenantsEnv })}
            </span>
          ) : null}
        </div>
      </TableCell>
      <TableCell className="min-w-72 align-top whitespace-normal">
        <div className="flex flex-col gap-1">
          <span className="text-fg">{row.description}</span>
          <span className="text-xs text-fg-muted">
            {t("flags.removal", { removal: row.removal })}
          </span>
        </div>
      </TableCell>
      <TableCell className="align-top">
        <Code>{row.owner}</Code>
      </TableCell>
      <TableCell className="align-top">
        <DefaultCell row={row} />
      </TableCell>
      <TableCell className="align-top">
        <ValueCell row={row} />
      </TableCell>
      <TableCell className="align-top">
        <ExpiryCell row={row} />
      </TableCell>
    </TableRow>
  );
}

/**
 * The flag console: every rollout switch in the shared registry with what it does, its owner
 * and default, when it must be removed (a badge once the date is near or past), and, for the
 * flags the web app reads, the value the web server's reader answers. Nothing here changes a
 * flag; the intro says where a flag is changed.
 */
export function FlagsView({ title, crumbs, view }: FlagsViewProps) {
  const { provider, rows, summary } = view;
  return (
    <div data-slot="flags" className="flex flex-col gap-6">
      <PageHeader
        title={title}
        description={t("flags.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      {provider.ok ? (
        <p data-slot="flag-provider" className="max-w-prose text-sm text-fg-muted">
          {t("flags.provider", { provider: provider.provider })}
        </p>
      ) : (
        <ErrorState title={t("flags.providerFailed")} detail={provider.reason} />
      )}
      {rows.length === 0 ? (
        <EmptyState title={t("flags.emptyTitle")} body={t("flags.emptyBody")} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label={t("flags.stat.total")} value={summary.total} tone="info" />
            <StatCard
              label={t("flags.stat.webOn")}
              value={summary.webOn}
              tone="success"
              hint={t("flags.stat.webOnHint", { count: summary.web })}
            />
            <StatCard
              label={t("flags.stat.soon", { days: EXPIRY_WARNING_DAYS })}
              value={summary.expiringSoon}
              tone={summary.expiringSoon > 0 ? "warning" : "neutral"}
            />
            <StatCard
              label={t("flags.stat.expired")}
              value={summary.expired}
              tone={summary.expired > 0 ? "danger" : "neutral"}
            />
          </div>
          <Table scrollLabel={t("flags.tableRegion")}>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("flags.caption", { count: rows.length })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("flags.column.flag")}</TableHead>
                <TableHead>{t("flags.column.description")}</TableHead>
                <TableHead>{t("flags.column.owner")}</TableHead>
                <TableHead>{t("flags.column.default")}</TableHead>
                <TableHead>{t("flags.column.value")}</TableHead>
                <TableHead>{t("flags.column.expires")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <FlagTableRow key={row.name} row={row} />
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  );
}
