import {
  Button,
  EmptyState,
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
import type { SelectOption } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { SettingsHeader } from "@/shared/ui/settings-header";
import {
  DIGEST_FIELDS,
  DIGEST_MODE_LABEL,
  DIGEST_MODE_TONE,
  digestCounts,
  digestModeOptions,
  sortRecipients,
} from "../model/digests";
import type { DigestRecipient } from "../model/digests";

type FormAction = (formData: FormData) => Promise<void>;

export interface DigestsViewProps {
  title: string;
  recipients: readonly DigestRecipient[];
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
  /**
   * Saves one person's digest mode, submitted as DIGEST_FIELDS.recipientId and
   * DIGEST_FIELDS.mode; without it each mode is shown but cannot be changed.
   */
  saveAction?: FormAction;
}

function ModeForm({
  recipient,
  options,
  action,
}: {
  recipient: DigestRecipient;
  options: readonly SelectOption[];
  action: FormAction;
}) {
  return (
    <form action={action} className="flex items-center gap-2">
      <input type="hidden" name={DIGEST_FIELDS.recipientId} value={recipient.id} />
      <Select
        name={DIGEST_FIELDS.mode}
        defaultValue={recipient.mode}
        options={options}
        aria-label={t("caSettings.digests.modeFor", { name: recipient.name })}
        className="w-56"
      />
      <Button type="submit" variant="secondary" size="sm">
        {t("common.save")} <span className="sr-only">{recipient.name}</span>
      </Button>
    </form>
  );
}

function RecipientRow({
  recipient,
  options,
  saveAction,
}: {
  recipient: DigestRecipient;
  options: readonly SelectOption[];
  saveAction?: FormAction;
}) {
  return (
    <TableRow data-recipient={recipient.id}>
      <TableCell>
        <span className="block font-medium text-fg">{recipient.name}</span>
        <span className="block text-xs text-fg-muted">{recipient.address}</span>
      </TableCell>
      <TableCell>{recipient.clientCount}</TableCell>
      <TableCell>
        {saveAction === undefined ? (
          <StatusChip
            status={recipient.mode}
            tone={DIGEST_MODE_TONE[recipient.mode]}
            label={t(DIGEST_MODE_LABEL[recipient.mode])}
          />
        ) : (
          <ModeForm recipient={recipient} options={options} action={saveAction} />
        )}
      </TableCell>
      <TableCell className="text-fg-muted">
        {recipient.lastSentAt === null
          ? t("caSettings.never")
          : formatDateTime(recipient.lastSentAt)}
      </TableCell>
    </TableRow>
  );
}

/**
 * The digests settings page: the settings header, then everyone at the firm who hears about its
 * clients, by name, with how many clients they hear about, whether they get the daily digest or
 * each change on its own (a choice they can change when saving is possible) and their last digest.
 */
export function DigestsView({ title, recipients, crumbs, tabs, saveAction }: DigestsViewProps) {
  const counts = digestCounts(recipients);
  const options = digestModeOptions();
  return (
    <div data-slot="ca-digests" className="flex flex-col gap-6">
      <SettingsHeader
        title={title}
        description={t("caSettings.digests.intro")}
        crumbs={crumbs}
        tabs={tabs}
      />
      {recipients.length === 0 ? (
        <EmptyState
          title={t("caSettings.digests.emptyTitle")}
          body={t("caSettings.digests.emptyBody")}
        />
      ) : (
        <Table>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("caSettings.digests.caption", { daily: counts.daily, total: counts.total })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("caSettings.digests.column.person")}</TableHead>
              <TableHead>{t("caSettings.digests.column.clients")}</TableHead>
              <TableHead>{t("caSettings.digests.column.mode")}</TableHead>
              <TableHead>{t("caSettings.digests.column.lastSent")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortRecipients(recipients).map((recipient) => (
              <RecipientRow
                key={recipient.id}
                recipient={recipient}
                options={options}
                saveAction={saveAction}
              />
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
