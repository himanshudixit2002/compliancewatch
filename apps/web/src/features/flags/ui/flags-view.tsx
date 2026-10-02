import {
  Badge,
  EmptyState,
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
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import { flagSummary, isExpired } from "../model/flags";
import type { FlagView } from "../model/flags";

export interface FlagsViewProps {
  title: string;
  flags: readonly FlagView[];
  /** Today as a YYYY-MM-DD key, to mark flags past their expiry date. */
  today: string;
}

function FlagRow({ flag, today }: { flag: FlagView; today: string }) {
  const expired = isExpired(flag, today);
  return (
    <TableRow data-flag={flag.name}>
      <TableCell className="align-top">
        <div className="flex flex-col gap-1">
          <code className="font-mono text-xs font-medium text-fg">{flag.name}</code>
          <span className="text-xs text-fg-muted">{t("flags.override", { env: flag.env })}</span>
        </div>
      </TableCell>
      <TableCell className="align-top whitespace-normal">
        <div className="flex flex-col gap-1">
          <span className="text-fg">{flag.description}</span>
          <span className="text-xs text-fg-muted">
            {t("flags.removal", { removal: flag.removal })}
          </span>
        </div>
      </TableCell>
      <TableCell className="align-top">
        <code className="font-mono text-xs text-fg">{flag.owner}</code>
      </TableCell>
      <TableCell className="align-top">
        <StatusChip
          status={flag.enabled ? "on" : "off"}
          tone={flag.enabled ? "success" : "neutral"}
          label={flag.enabled ? t("flags.state.on") : t("flags.state.off")}
        />
      </TableCell>
      <TableCell className="align-top">
        <div className="flex flex-col items-start gap-1">
          <span className={expired ? "text-fg" : "text-fg-muted"}>{formatDate(flag.expires)}</span>
          {expired ? <Badge tone="danger">{t("flags.expired")}</Badge> : null}
        </div>
      </TableCell>
    </TableRow>
  );
}

/**
 * The admin flags page: a summary row (flags, flags on, flags past their expiry), then every
 * web flag with its registry description and removal condition, owner, state and expiry.
 */
export function FlagsView({ title, flags, today }: FlagsViewProps) {
  const summary = flagSummary(flags, today);
  return (
    <div data-slot="flags" className="flex flex-col gap-6">
      <PageHeader title={title} description={t("flags.intro")} />
      {flags.length === 0 ? (
        <EmptyState title={t("flags.emptyTitle")} body={t("flags.emptyBody")} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <StatCard label={t("flags.stat.total")} value={summary.total} tone="info" />
            <StatCard label={t("flags.stat.enabled")} value={summary.enabled} tone="success" />
            <StatCard
              label={t("flags.stat.expired")}
              value={summary.expired}
              tone={summary.expired > 0 ? "danger" : "neutral"}
            />
          </div>
          <Table>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("flags.caption", { count: flags.length })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("flags.column.flag")}</TableHead>
                <TableHead>{t("flags.column.description")}</TableHead>
                <TableHead>{t("flags.column.owner")}</TableHead>
                <TableHead>{t("flags.column.state")}</TableHead>
                <TableHead>{t("flags.column.expires")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {flags.map((flag) => (
                <FlagRow key={flag.name} flag={flag} today={today} />
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  );
}
