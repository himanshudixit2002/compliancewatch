import {
  Badge,
  EmptyState,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { SettingsHeader } from "@/shared/ui/settings-header";
import { StatCard } from "@/shared/ui/stat-card";
import {
  CHANNEL_LABEL,
  ROLE_LABEL,
  languageName,
  recipientSummary,
  sortRecipients,
} from "../model/recipients";
import type { Recipient } from "../model/recipients";

export interface RecipientsViewProps {
  title: string;
  recipients: readonly Recipient[];
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
}

function None() {
  return <span className="text-fg-muted">{t("common.none")}</span>;
}

function RecipientRow({ recipient }: { recipient: Recipient }) {
  return (
    <TableRow data-recipient={recipient.id}>
      <TableCell className="align-top">
        <div className="flex flex-col items-start gap-1">
          <span className="font-medium text-fg">
            {recipient.orgLabel === "" ? t("recipients.unnamed") : recipient.orgLabel}
          </span>
          <Badge tone="neutral">{t(ROLE_LABEL[recipient.role])}</Badge>
        </div>
      </TableCell>
      <TableCell className="align-top">
        {recipient.addresses.length === 0 ? (
          <None />
        ) : (
          <ol className="flex flex-col gap-1">
            {recipient.addresses.map((address) => (
              <li key={`${address.channel} ${address.address}`} className="flex items-center gap-2">
                <Badge tone="info">{t(CHANNEL_LABEL[address.channel])}</Badge>
                <span className="font-mono text-xs">{address.address}</span>
              </li>
            ))}
          </ol>
        )}
      </TableCell>
      <TableCell className="align-top whitespace-normal">
        {recipient.businesses.length === 0 ? <None /> : recipient.businesses.join(", ")}
      </TableCell>
      <TableCell className="align-top">{languageName(recipient.language)}</TableCell>
      <TableCell className="align-top">
        {recipient.byDigest ? t("recipients.delivery.digest") : t("recipients.delivery.immediate")}
      </TableCell>
      <TableCell className="align-top text-fg-muted">{formatDate(recipient.updatedAt)}</TableCell>
    </TableRow>
  );
}

/**
 * The notification recipients page: the settings header, a summary row (recipients, on
 * WhatsApp, on email, on the daily digest), then each recipient with its organisation and
 * role, addresses in the order they are tried, businesses, language, delivery and last change.
 */
export function RecipientsView({ title, recipients, crumbs, tabs }: RecipientsViewProps) {
  const summary = recipientSummary(recipients);
  return (
    <div data-slot="recipients" className="flex flex-col gap-6">
      <SettingsHeader
        title={title}
        description={t("recipients.intro")}
        crumbs={crumbs}
        tabs={tabs}
      />
      {recipients.length === 0 ? (
        <EmptyState title={t("recipients.emptyTitle")} body={t("recipients.emptyBody")} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label={t("recipients.stat.total")} value={summary.total} tone="info" />
            <StatCard label={t("recipients.stat.whatsapp")} value={summary.whatsapp} />
            <StatCard label={t("recipients.stat.email")} value={summary.email} />
            <StatCard label={t("recipients.stat.digest")} value={summary.byDigest} />
          </div>
          <Table>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("recipients.caption", { count: recipients.length })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("recipients.column.recipient")}</TableHead>
                <TableHead>{t("recipients.column.addresses")}</TableHead>
                <TableHead>{t("recipients.column.businesses")}</TableHead>
                <TableHead>{t("recipients.column.language")}</TableHead>
                <TableHead>{t("recipients.column.delivery")}</TableHead>
                <TableHead>{t("recipients.column.updatedAt")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortRecipients(recipients).map((recipient) => (
                <RecipientRow key={recipient.id} recipient={recipient} />
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  );
}
