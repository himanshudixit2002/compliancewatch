"use server";

import { stateOf } from "@/entities/consent/mappers";
import { recipientLabel } from "@/entities/notification/mappers";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import {
  forgetRecipient as forgetRememberedRecipient,
  readRememberedRecipients,
  rememberRecipient,
} from "@/server/remembered-recipients";
import { toActionState } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import {
  actionFailure,
  actionSuccess,
  fieldFailure,
  type ActionState,
} from "@/shared/lib/action-state";
import { formatDateTime } from "@/shared/lib/dates";
import { notificationPreferencesGateway } from "./gateway";
import { CHANNEL_PURPOSE, channelLabel, parseRecipient } from "./model/channels";
import { languagesFor } from "./model/languages";
import {
  PREFERENCE_FIELDS,
  RECIPIENT_FIELDS,
  parsePreferenceForm,
  parseRecipientForm,
  readChannel,
  type ParsedForm,
} from "./model/preference-form";
import { describeQuietHours } from "./model/quiet-hours";

/**
 * The notifications page's server actions. Each runs the screen's gate again (the proxy never
 * sees an action). Choosing a recipient checks the number or address and remembers it on this
 * device (server/remembered-recipients.ts); the page then reads that recipient's preference.
 * Saving a preference replaces it on the notification service with `source: web_onboarding`
 * (its sources have no settings value), the language and both ends of the quiet hours, for the
 * recipient the page showed. Opting in needs the user's consent to the channel's reminders to be
 * on file, as the consent step records it before it opts a number in; opting out never waits
 * on anything.
 */
const SCREEN_ID = "owner.settings.notifications";

function refused<T>(parsed: Extract<ParsedForm<unknown>, { ok: false }>): ActionState<T> {
  if (parsed.fieldErrors !== undefined) {
    return parsed.formErrors === undefined
      ? fieldFailure(parsed.fieldErrors)
      : actionFailure(parsed.formErrors, parsed.fieldErrors);
  }
  return actionFailure(parsed.formErrors ?? []);
}

export async function chooseRecipient(
  _state: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const screen = screenById(SCREEN_ID);
  const session = await requireScreenSession(screen);
  const parsed = parseRecipientForm(formData);
  if (!parsed.ok) return refused(parsed);
  const recipient = parseRecipient(parsed.value.channel, parsed.value.recipient);
  if (!recipient.ok) return fieldFailure({ [RECIPIENT_FIELDS.recipient]: [recipient.error] });
  await rememberRecipient(session.userId, parsed.value.channel, recipient.key);
  afterMutation({ paths: [hrefFor(screen)] });
  return actionSuccess(undefined);
}

/** "Use another number": forgets the channel's recipient on this device. A plain form action. */
export async function forgetRecipient(formData: FormData): Promise<void> {
  const screen = screenById(SCREEN_ID);
  const session = await requireScreenSession(screen);
  const channel = readChannel(formData);
  if (channel === null) return;
  await forgetRememberedRecipient(session.userId, channel);
  afterMutation({ paths: [hrefFor(screen)] });
}

export async function savePreference(
  _state: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const screen = screenById(SCREEN_ID);
  const session = await requireScreenSession(screen);
  const channel = readChannel(formData);
  if (channel === null) return actionFailure(t("notifications.error.channel"));
  const recipient = (await readRememberedRecipients(session.userId))[channel];
  if (recipient === undefined) {
    return actionFailure(t("notifications.error.noRecipient", { channel: channelLabel(channel) }));
  }

  const gateway = notificationPreferencesGateway({ session });
  const templates = await gateway.templates();
  if (!templates.ok) return toActionState(templates);
  const current = await gateway.preference(channel, recipient);
  const offered = languagesFor(
    channel,
    templates.value,
    current.ok ? current.value?.language : undefined,
  ).map((option) => option.value);
  const parsed = parsePreferenceForm(formData, offered);
  if (!parsed.ok) return refused(parsed);
  const choice = parsed.value;

  if (choice.optedIn) {
    const consents = await gateway.consents(session.userId);
    if (!consents.ok) return toActionState(consents);
    const purpose = CHANNEL_PURPOSE[channel];
    if (stateOf(consents.value, purpose)?.granted !== true) {
      return actionFailure(
        t("notifications.error.consentMissing", {
          purpose: t(`consent.purpose.${purpose}`),
        }),
        { [PREFERENCE_FIELDS.optedIn]: [t("notifications.error.consentMissingField")] },
      );
    }
  }

  const saved = await gateway.save(channel, recipient, {
    optedIn: choice.optedIn,
    source: "web_onboarding",
    language: choice.language,
    quietHoursStart: choice.quietHoursStart,
    quietHoursEnd: choice.quietHoursEnd,
  });
  if (!saved.ok) return toActionState(saved);
  afterMutation({ paths: [hrefFor(screen)] });
  return actionSuccess(
    undefined,
    t("notifications.saved", {
      recipient: recipientLabel(channel, recipient),
      status: saved.value.optedIn ? t("notifications.optedIn") : t("notifications.optedOut"),
      quiet: describeQuietHours(saved.value.quietHoursStart, saved.value.quietHoursEnd),
      date: formatDateTime(saved.value.updatedAt),
    }),
  );
}
