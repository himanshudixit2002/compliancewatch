import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  Banner,
  Button,
  EmptyState,
  Field,
  Select,
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
import { withQuery } from "@/shared/lib/url";
import { SettingsHeader } from "@/shared/ui/settings-header";
import { StatCard } from "@/shared/ui/stat-card";
import { BUSINESS_CHOICES, RECIPIENTS_PAGE_SIZE } from "../model/page";
import type { RecipientRow, RecipientsPageView } from "../model/page";
import {
  ADDRESS_CHANNELS,
  RECIPIENT_FIELDS,
  addressField,
  channelField,
} from "../model/recipient-form";
import { CHANNEL_LABEL, DIGEST_LABEL, DIGEST_MODES } from "../model/recipients";
import { RecipientForm, type RecipientFormAction } from "./recipient-form";
import { RemoveRecipient, type RemoveRecipientAction } from "./remove-recipient";

export interface RecipientsViewProps {
  title: string;
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
  view: RecipientsPageView;
  /** The page itself, without a query. */
  pageHref: string;
  /** What the last action did: the recipient saved, or a removal. */
  status: { saved?: string; removed?: boolean };
  saveAction: RecipientFormAction;
  removeAction: RemoveRecipientAction;
  /** Where a tenant without a business adds one. */
  addBusinessHref: string;
}

function rowName(row: RecipientRow): string {
  return row.orgLabel === "" ? row.roleLabel : row.orgLabel;
}

function StatusLine({ view, status }: Pick<RecipientsViewProps, "view" | "status">) {
  if (status.removed === true) {
    return <Banner tone="success" title={t("recipients.removed")} />;
  }
  if (status.saved === undefined) return null;
  const row = view.rows.find((candidate) => candidate.id === status.saved);
  return (
    <Banner
      tone="success"
      title={
        row === undefined
          ? t("recipients.savedOther")
          : t("recipients.saved", { name: rowName(row) })
      }
    />
  );
}

function RecipientsTable({
  view,
  removeAction,
}: Pick<RecipientsViewProps, "view" | "removeAction">) {
  const business = view.selected?.id ?? "";
  return (
    <Table scrollLabel={t("recipients.tableRegion")}>
      <TableCaption className="text-left text-sm text-fg-muted">
        {t("recipients.caption", { count: view.rows.length })}
      </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{t("recipients.column.recipient")}</TableHead>
          <TableHead>{t("recipients.column.addresses")}</TableHead>
          <TableHead>{t("recipients.column.businesses")}</TableHead>
          <TableHead>{t("recipients.column.language")}</TableHead>
          <TableHead>{t("recipients.column.delivery")}</TableHead>
          <TableHead>{t("recipients.column.updatedAt")}</TableHead>
          <TableHead>{t("recipients.column.actions")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {view.rows.map((row) => (
          <TableRow key={row.id} data-recipient={row.id}>
            <TableCell className="align-top">
              <div className="flex flex-col items-start gap-1">
                <span className="font-medium text-fg">
                  {row.orgLabel === "" ? t("recipients.unnamed") : row.orgLabel}
                </span>
                <Badge tone="neutral">{row.roleLabel}</Badge>
              </div>
            </TableCell>
            <TableCell className="align-top">
              {row.addresses.length === 0 ? (
                <span className="text-fg-muted">{t("common.none")}</span>
              ) : (
                <ol className="flex flex-col gap-1">
                  {row.addresses.map((address) => (
                    <li
                      key={`${address.channel} ${address.address}`}
                      className="flex items-center gap-2"
                    >
                      <Badge tone="info">{address.channelLabel}</Badge>
                      <span className="font-mono text-xs">{address.address}</span>
                    </li>
                  ))}
                </ol>
              )}
            </TableCell>
            <TableCell className="align-top whitespace-normal">
              {row.businesses.join(", ")}
            </TableCell>
            <TableCell className="align-top">{row.languageLabel}</TableCell>
            <TableCell className="align-top">{row.deliveryLabel}</TableCell>
            <TableCell className="align-top text-fg-muted">{formatDate(row.updatedAt)}</TableCell>
            <TableCell className="align-top">
              <div className="flex flex-wrap items-center gap-2">
                <Link
                  href={row.editHref as Route}
                  aria-label={t("recipients.changeLabel", { name: rowName(row) })}
                  className="text-sm text-primary underline-offset-2 hover:underline"
                >
                  {t("recipients.change")}
                </Link>
                <RemoveRecipient
                  action={removeAction}
                  recipientId={row.id}
                  name={rowName(row)}
                  returnBusiness={business}
                  fields={{
                    recipientId: RECIPIENT_FIELDS.recipientId,
                    returnBusiness: RECIPIENT_FIELDS.returnBusiness,
                  }}
                />
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * The notification recipients page: the settings header, what the last action did, the business
 * whose recipients are shown (chosen with a GET form, since a business id is not personal data),
 * a summary row and each recipient with its addresses in the order they are tried, the businesses
 * it hears about, its language and delivery, with Change and Remove; then the form to add one
 * or change the one chosen. A tenant without a business is told to add one first.
 */
export function RecipientsView({
  title,
  crumbs,
  tabs,
  view,
  pageHref,
  status,
  saveAction,
  removeAction,
  addBusinessHref,
}: RecipientsViewProps) {
  const { selected, form } = view;
  return (
    <div data-slot="recipients" className="flex max-w-5xl flex-col gap-6">
      <SettingsHeader
        title={title}
        description={t("recipients.intro")}
        crumbs={crumbs}
        tabs={tabs}
      />
      <StatusLine view={view} status={status} />
      {selected === null || form === null ? (
        <EmptyState
          title={t("recipients.noBusinessTitle")}
          body={t("recipients.noBusinessBody")}
          action={
            <Button asChild variant="secondary" size="sm">
              <Link href={addBusinessHref as Route}>{t("recipients.addBusiness")}</Link>
            </Button>
          }
        />
      ) : (
        <>
          {view.businesses.length > 1 ? (
            <form
              method="get"
              action={pageHref}
              aria-label={t("recipients.pickerLabel")}
              data-slot="business-picker"
              className="flex flex-wrap items-end gap-2"
            >
              <Field id="recipients-business" label={t("recipients.business")} className="w-72">
                <Select
                  name="business"
                  defaultValue={selected.id}
                  options={view.businesses.map((business) => ({
                    value: business.id,
                    label: business.name,
                  }))}
                />
              </Field>
              <Button type="submit" variant="secondary" size="sm">
                {t("recipients.showBusiness")}
              </Button>
            </form>
          ) : null}
          {view.moreBusinesses ? (
            <p className="text-sm text-fg-muted">
              {t("recipients.moreBusinesses", { count: BUSINESS_CHOICES })}
            </p>
          ) : null}
          <section aria-labelledby="recipients-list" className="flex flex-col gap-4">
            <h2 id="recipients-list" className="text-lg font-semibold text-fg">
              {t("recipients.ofBusiness", { name: selected.name })}
            </h2>
            {view.rows.length === 0 ? (
              <EmptyState title={t("recipients.emptyTitle")} body={t("recipients.emptyBody")} />
            ) : (
              <>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <StatCard
                    label={t("recipients.stat.total")}
                    value={view.summary.total}
                    tone="info"
                  />
                  <StatCard label={t("recipients.stat.whatsapp")} value={view.summary.whatsapp} />
                  <StatCard label={t("recipients.stat.email")} value={view.summary.email} />
                  <StatCard label={t("recipients.stat.digest")} value={view.summary.byDigest} />
                </div>
                <RecipientsTable view={view} removeAction={removeAction} />
                {view.moreRecipients ? (
                  <p className="text-sm text-fg-muted">
                    {t("recipients.moreRecipients", { count: RECIPIENTS_PAGE_SIZE })}
                  </p>
                ) : null}
              </>
            )}
          </section>
          <section aria-labelledby="recipient-form-heading" className="flex flex-col gap-4">
            <h2 id="recipient-form-heading" className="text-lg font-semibold text-fg">
              {form.mode === "add"
                ? t("recipients.formAdd")
                : t("recipients.formChange", { name: form.name })}
            </h2>
            {view.editMissing ? (
              <Banner tone="warning" title={t("recipients.editMissing")} />
            ) : null}
            <RecipientForm
              key={form.recipientId}
              action={saveAction}
              form={form}
              returnBusiness={selected.id}
              fields={{
                ...RECIPIENT_FIELDS,
                addresses: Array.from({ length: form.addressRows }, (_, index) =>
                  addressField(index),
                ),
                channels: Array.from({ length: form.addressRows }, (_, index) =>
                  channelField(index),
                ),
              }}
              channels={ADDRESS_CHANNELS.map((channel) => ({
                value: channel,
                label: t(CHANNEL_LABEL[channel]),
              }))}
              digestModes={DIGEST_MODES.map((mode) => ({
                value: mode,
                label: t(DIGEST_LABEL[mode]),
              }))}
              cancelHref={
                form.mode === "change" ? withQuery(pageHref, { business: selected.id }) : null
              }
            />
          </section>
        </>
      )}
    </div>
  );
}
