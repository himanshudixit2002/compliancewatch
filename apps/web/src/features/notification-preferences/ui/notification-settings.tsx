import type { Route } from "next";
import Link from "next/link";
import { Banner, Button, KeyValue } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { ServiceError } from "@/shared/ui/service-error";
import { SettingsHeader } from "@/shared/ui/settings-header";
import type { ChannelView, NotificationSettingsView } from "../model/view";
import { PreferenceForm, type PreferenceAction, type PreferenceFormProps } from "./preference-form";
import { RecipientForm, type RecipientAction, type RecipientFormProps } from "./recipient-form";

export interface NotificationSettingsProps {
  title: string;
  view: NotificationSettingsView;
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
  chooseRecipient: RecipientAction;
  /** A plain form action: forgets the channel's recipient on this device. */
  forgetRecipient: (formData: FormData) => Promise<void>;
  savePreference: PreferenceAction;
  fields: { recipient: RecipientFormProps["fields"]; preference: PreferenceFormProps["fields"] };
  consentsHref: string;
}

function ChannelSection({
  channel,
  props,
}: {
  channel: ChannelView;
  props: NotificationSettingsProps;
}) {
  const headingId = `channel-${channel.channel}`;
  const { state } = channel;
  return (
    <section
      aria-labelledby={headingId}
      data-slot="channel"
      data-channel={channel.channel}
      className="flex flex-col gap-4 rounded-md border border-line bg-surface p-4"
    >
      <h2 id={headingId} className="text-lg font-semibold text-fg">
        {channel.title}
      </h2>
      <p className="text-sm text-fg-muted" data-slot="channel-consent">
        {channel.consentGiven
          ? t("notifications.consentGiven", { purpose: channel.purposeLabel })
          : t("notifications.consentNotGiven", { purpose: channel.purposeLabel })}{" "}
        <Link href={props.consentsHref as Route} className="text-primary underline">
          {t("notifications.toConsents")}
        </Link>
      </p>
      {channel.channel === "email" ? (
        <p className="text-sm text-fg-muted" data-slot="email-note">
          {t("notifications.emailNote")}
        </p>
      ) : null}
      {channel.recipient === null ? (
        <RecipientForm
          action={props.chooseRecipient}
          channel={channel.channel}
          label={channel.recipientField}
          formLabel={t("notifications.recipientFormLabel", { channel: channel.title })}
          help={t(`notifications.recipientHelp.${channel.channel}`)}
          inputType={channel.channel === "whatsapp" ? "tel" : "email"}
          fields={props.fields.recipient}
        />
      ) : (
        <>
          <form
            action={props.forgetRecipient}
            className="flex flex-wrap items-center gap-3"
            data-slot="recipient"
          >
            <input type="hidden" name={props.fields.recipient.channel} value={channel.channel} />
            <p className="text-sm text-fg">
              {channel.recipientField}: <span className="font-medium">{channel.recipient}</span>
            </p>
            <Button type="submit" variant="ghost" size="sm">
              {t(`notifications.another.${channel.channel}`)}
            </Button>
          </form>
          {state.kind === "error" ? <ServiceError error={state.error} /> : null}
          {state.kind === "not_recorded" ? (
            <Banner tone="info" title={t("notifications.notRecordedTitle")}>
              {t("notifications.notRecorded")}
            </Banner>
          ) : null}
          {state.kind === "recorded" ? (
            <KeyValue
              data-slot="preference"
              items={[
                {
                  key: "status",
                  label: t("notifications.field.status"),
                  value: state.preference.statusLabel,
                },
                {
                  key: "language",
                  label: t("notifications.field.language"),
                  value: state.preference.languageLabel,
                },
                {
                  key: "quiet",
                  label: t("notifications.field.quiet"),
                  value: state.preference.quietHours,
                },
                {
                  key: "source",
                  label: t("notifications.field.source"),
                  value: state.preference.source,
                },
                {
                  key: "updated",
                  label: t("notifications.field.updated"),
                  value: state.preference.updatedAt,
                },
              ]}
            />
          ) : null}
          {state.kind === "error" ? null : (
            <PreferenceForm
              action={props.savePreference}
              channel={channel.channel}
              recipient={channel.recipient}
              fields={props.fields.preference}
              values={channel.form}
              languages={channel.languages}
              consentGiven={channel.consentGiven}
              purposeLabel={channel.purposeLabel}
              consentsHref={props.consentsHref}
            />
          )}
        </>
      )}
    </section>
  );
}

/**
 * The notifications page: one section per channel (WhatsApp, then email) with the user's
 * consent to that channel's reminders, the recipient chosen on this device, what the
 * notification service holds for it, and the form that replaces it. Until the identity service
 * returns the user's own number and address, the page asks for them and remembers them here.
 */
export function NotificationSettings(props: NotificationSettingsProps) {
  const { title, view, crumbs, tabs } = props;
  return (
    <div data-slot="notification-settings" className="flex max-w-4xl flex-col gap-6">
      <SettingsHeader
        title={title}
        description={t("notifications.intro")}
        crumbs={crumbs}
        tabs={tabs}
      />
      <p className="max-w-prose text-sm text-fg-muted">{t("notifications.recipientNote")}</p>
      {view.channels.map((channel) => (
        <ChannelSection key={channel.channel} channel={channel} props={props} />
      ))}
    </div>
  );
}
