import type { ReactNode } from "react";
import type { Route } from "next";
import Link from "next/link";
import { Banner, KeyValue, StatusChip } from "@compliancewatch/ui";
import type { KeyValueItem } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import type { NotificationDetailView } from "../model/notifications";

export interface NotificationDetailProps {
  detail: NotificationDetailView;
  /** The notification this one falls back from, when it is one. */
  fallbackHref: string | null;
  /** The ids an operator traces a delivery by: business, obligation, recipient, dispatch. */
  showIds?: boolean;
  /** Anything the page adds under the record, such as what an action waits for. */
  children?: ReactNode;
}

function Code({ children }: { children: string }) {
  return <code className="font-mono text-xs">{children}</code>;
}

function when(at: string | null): string {
  return at === null ? t("notificationLog.notYet") : formatDateTime(at);
}

/**
 * One notification's record as the service keeps it: the channel's last error first, then the
 * delivery state, where it went, what it was, the attempts and every time it moved, and the
 * values the message was filled with. The service keeps no copy of the message's text.
 */
export function NotificationDetail({
  detail,
  fallbackHref,
  showIds = false,
  children,
}: NotificationDetailProps) {
  const items: KeyValueItem[] = [
    {
      key: "state",
      label: t("notificationLog.field.state"),
      value: <StatusChip status={detail.state} tone={detail.tone} label={detail.stateLabel} />,
    },
    { key: "channel", label: t("notificationLog.field.channel"), value: detail.channelLabel },
    { key: "to", label: t("notificationLog.field.to"), value: <Code>{detail.to}</Code> },
    { key: "occasion", label: t("notificationLog.field.occasion"), value: detail.occasionLabel },
    {
      key: "template",
      label: t("notificationLog.field.template"),
      value: <Code>{detail.templateKey}</Code>,
    },
    { key: "language", label: t("notificationLog.field.language"), value: detail.languageLabel },
    { key: "attempts", label: t("notificationLog.field.attempts"), value: String(detail.attempts) },
    ...detail.times.map((time) => ({ key: time.key, label: time.label, value: when(time.at) })),
  ];
  if (fallbackHref !== null && detail.fallbackOf !== null) {
    items.push({
      key: "fallbackOf",
      label: t("notificationLog.field.fallbackOf"),
      value: (
        <Link
          href={fallbackHref as Route}
          className="text-primary underline-offset-2 hover:underline"
        >
          {detail.fallbackOf}
        </Link>
      ),
    });
  }
  if (showIds) {
    items.push(
      {
        key: "business",
        label: t("notificationLog.field.business"),
        value: <Code>{detail.businessId}</Code>,
      },
      {
        key: "obligation",
        label: t("notificationLog.field.obligation"),
        value: <Code>{detail.obligationId}</Code>,
      },
      {
        key: "recipient",
        label: t("notificationLog.field.recipient"),
        value:
          detail.recipientId === null ? (
            t("notificationLog.noRecipient")
          ) : (
            <Code>{detail.recipientId}</Code>
          ),
      },
      {
        key: "dispatch",
        label: t("notificationLog.field.dispatch"),
        value: detail.dispatchId === null ? t("common.none") : <Code>{detail.dispatchId}</Code>,
      },
      {
        key: "provider",
        label: t("notificationLog.field.provider"),
        value:
          detail.providerMessageId === "" ? (
            t("common.none")
          ) : (
            <Code>{detail.providerMessageId}</Code>
          ),
      },
    );
  }
  items.push({
    key: "id",
    label: t("notificationLog.field.id"),
    value: <Code>{detail.id}</Code>,
    copy: detail.id,
  });
  return (
    <div data-slot="notification-detail" className="flex flex-col gap-6">
      {detail.error === "" ? null : (
        <Banner
          tone={detail.state === "failed" ? "danger" : "warning"}
          title={t("notificationLog.errorTitle")}
        >
          <span data-slot="notification-error">{detail.error}</span>
        </Banner>
      )}
      <KeyValue items={items} aria-label={t("notificationLog.field.section")} />
      <section aria-labelledby="notification-params" className="flex flex-col gap-2">
        <h2 id="notification-params" className="text-base font-semibold text-fg">
          {t("notificationLog.paramsTitle")}
        </h2>
        {detail.params.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("notificationLog.paramsNone")}</p>
        ) : (
          <KeyValue
            items={detail.params.map((param) => ({
              key: param.key,
              label: <Code>{param.key}</Code>,
              value: param.value,
            }))}
            aria-label={t("notificationLog.paramsTitle")}
          />
        )}
      </section>
      {children}
    </div>
  );
}
