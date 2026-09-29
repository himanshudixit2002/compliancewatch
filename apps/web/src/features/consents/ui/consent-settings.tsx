import type { Route } from "next";
import Link from "next/link";
import {
  Banner,
  Button,
  DRAFT_BANNER_TEXT,
  EmptyState,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { Tone } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { SettingsHeader } from "@/shared/ui/settings-header";
import type {
  ConsentHistoryItem,
  ConsentRowView,
  ConsentSettingsView,
  ConsentStatus,
} from "../model/settings";
import { ConsentChange, type ConsentChangeAction } from "./consent-change";

export interface ConsentSettingsProps<R> {
  title: string;
  view: ConsentSettingsView;
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
  action: ConsentChangeAction<R>;
  fields: { purpose: string; change: string; number: string };
  /** The consent step, for the roles that have it; null otherwise. */
  onboardingHref: string | null;
  dataRightsHref: string;
  /** The page of a legal document, by its docs/legal name. */
  documentHref: (name: string) => string;
}

const STATUS_TONES: Readonly<Record<ConsentStatus, Tone>> = {
  granted: "success",
  withdrawn: "warning",
  not_given: "neutral",
};

function StateCell({ row }: { row: ConsentRowView }) {
  return (
    <StatusChip
      status={row.status}
      tone={STATUS_TONES[row.status]}
      label={t(`consentSettings.status.${row.status}`)}
    />
  );
}

function recordsSentence(row: ConsentRowView): string {
  return row.change === "withdraw"
    ? t("consentSettings.recordsWithdraw", {
        purpose: row.label,
        notice: row.noticeVersion ?? t("consentSettings.noNotice"),
      })
    : t("consentSettings.recordsGive", { purpose: row.label, notice: row.currentNoticeVersion });
}

function recordedByText(item: ConsentHistoryItem): string {
  if (item.recordedBy === null) return t("consentSettings.recordedBy.none");
  return item.recordedBy === "you" ? t("consentSettings.recordedBy.you") : item.recordedBy;
}

/**
 * The consents settings page: the latest record for each purpose, with a way to give or
 * withdraw the optional ones, and every record oldest first. The required purposes say why they
 * are not changed here and where their withdrawal goes; a purpose given for an earlier version
 * of its document says so. While a document is a draft the draft banner names it.
 */
export function ConsentSettings<R>({
  title,
  view,
  crumbs,
  tabs,
  action,
  fields,
  onboardingHref,
  dataRightsHref,
  documentHref,
}: ConsentSettingsProps<R>) {
  return (
    <div data-slot="consent-settings" className="flex max-w-5xl flex-col gap-8">
      <SettingsHeader
        title={title}
        description={t("consentSettings.intro")}
        crumbs={crumbs}
        tabs={tabs}
      />
      {view.drafts.length > 0 ? (
        <Banner tone="warning" title={DRAFT_BANNER_TEXT} data-slot="draft-banner">
          {t("consentSettings.draft", {
            documents: view.drafts
              .map((document) => `${document.title} ${document.version}`)
              .join(", "),
          })}
        </Banner>
      ) : null}

      <section aria-labelledby="consent-state" className="flex flex-col gap-3">
        <h2 id="consent-state" className="text-lg font-semibold text-fg">
          {t("consentSettings.stateTitle")}
        </h2>
        <Table data-slot="consent-states" scrollLabel={t("consentSettings.stateCaption")}>
          <TableCaption>{t("consentSettings.stateCaption")}</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("consentSettings.column.purpose")}</TableHead>
              <TableHead>{t("consentSettings.column.state")}</TableHead>
              <TableHead>{t("consentSettings.column.notice")}</TableHead>
              <TableHead>{t("consentSettings.column.since")}</TableHead>
              <TableHead>{t("consentSettings.column.source")}</TableHead>
              <TableHead>{t("consentSettings.column.change")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {view.rows.map((row) => (
              <TableRow key={row.purpose} data-purpose={row.purpose} className="align-top">
                <TableCell className="font-medium">
                  <span className="block">{row.label}</span>
                  <Link
                    href={documentHref(row.document.name) as Route}
                    className="text-xs font-normal text-primary underline"
                  >
                    {t("consent.document", {
                      title: row.document.title,
                      version: row.document.version,
                    })}
                  </Link>
                </TableCell>
                <TableCell>
                  <StateCell row={row} />
                </TableCell>
                <TableCell>
                  <code className="text-xs">
                    {row.noticeVersion ?? t("consentSettings.noNotice")}
                  </code>
                  {row.outdated ? (
                    <p className="text-xs text-fg-muted" data-slot="consent-outdated">
                      {t("consentSettings.outdated", { current: row.currentNoticeVersion })}
                      {row.required && onboardingHref !== null ? (
                        <>
                          {" "}
                          <Link href={onboardingHref as Route} className="text-primary underline">
                            {t("consentSettings.agreeAgain")}
                          </Link>
                        </>
                      ) : null}
                    </p>
                  ) : null}
                </TableCell>
                <TableCell>{row.since ?? t("consentSettings.never")}</TableCell>
                <TableCell>{row.source ?? t("consentSettings.never")}</TableCell>
                <TableCell>
                  {row.change === null ? (
                    <span className="text-xs text-fg-muted">
                      {row.required
                        ? t("consentSettings.required")
                        : t("consentSettings.whatsappNotOffered")}
                    </span>
                  ) : (
                    <ConsentChange
                      action={action}
                      purpose={row.purpose}
                      purposeLabel={row.label}
                      change={row.change}
                      statement={row.statement}
                      records={recordsSentence(row)}
                      fields={fields}
                      {...(row.purpose === "whatsapp_reminders"
                        ? {
                            number: {
                              defaultValue: view.whatsappNumber,
                              required: row.change === "give",
                              help:
                                row.change === "give"
                                  ? t("consentSettings.numberGiveHelp")
                                  : t("consentSettings.numberWithdrawHelp"),
                            },
                          }
                        : {})}
                    />
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <p className="max-w-prose text-sm text-fg-muted" data-slot="consent-required-note">
          {t("consentSettings.requiredNote")}{" "}
          <Link href={dataRightsHref as Route} className="text-primary underline">
            {t("consentSettings.requiredLink")}
          </Link>
        </p>
      </section>

      <section aria-labelledby="consent-history" className="flex flex-col gap-3">
        <h2 id="consent-history" className="text-lg font-semibold text-fg">
          {t("consentSettings.historyTitle")}
        </h2>
        {view.history.length === 0 ? (
          <EmptyState
            heading="h3"
            title={t("consentSettings.emptyTitle")}
            body={
              onboardingHref === null
                ? t("consentSettings.emptyBodyNoStep")
                : t("consentSettings.emptyBody")
            }
            action={
              onboardingHref === null ? undefined : (
                <Button asChild variant="secondary">
                  <Link href={onboardingHref as Route}>{t("consentSettings.getStarted")}</Link>
                </Button>
              )
            }
          />
        ) : (
          <Table data-slot="consent-history" scrollLabel={t("consentSettings.historyCaption")}>
            <TableCaption>{t("consentSettings.historyCaption")}</TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("consentSettings.column.recordedAt")}</TableHead>
                <TableHead>{t("consentSettings.column.purpose")}</TableHead>
                <TableHead>{t("consentSettings.column.granted")}</TableHead>
                <TableHead>{t("consentSettings.column.notice")}</TableHead>
                <TableHead>{t("consentSettings.column.source")}</TableHead>
                <TableHead>{t("consentSettings.column.evidence")}</TableHead>
                <TableHead>{t("consentSettings.column.recordedBy")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.history.map((item) => (
                <TableRow key={item.id} data-record-id={item.id} className="align-top">
                  <TableCell className="whitespace-nowrap">{item.recordedAt}</TableCell>
                  <TableCell>{item.label}</TableCell>
                  <TableCell>
                    {item.granted
                      ? t("consentSettings.history.granted")
                      : t("consentSettings.history.withdrawn")}
                  </TableCell>
                  <TableCell>
                    <code className="text-xs">
                      {item.noticeVersion ?? t("consentSettings.noNotice")}
                    </code>
                  </TableCell>
                  <TableCell>{item.source}</TableCell>
                  <TableCell className="min-w-64 text-xs">{item.evidence}</TableCell>
                  <TableCell className="text-xs">{recordedByText(item)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
    </div>
  );
}
