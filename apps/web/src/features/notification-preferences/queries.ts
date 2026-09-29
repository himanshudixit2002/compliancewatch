import "server-only";

import { CHANNELS } from "@/entities/notification/mappers";
import type { Channel } from "@/entities/notification/types";
import type { ClientContext, ClientPrincipal } from "@/server/api/services";
import { readRememberedRecipients } from "@/server/remembered-recipients";
import { err, ok, type Result } from "@/server/result";
import { notificationPreferencesGateway } from "./gateway";
import {
  notificationSettingsView,
  type NotificationSettingsView,
  type PreferenceRead,
} from "./model/view";

/**
 * The notifications page's read: the recipients this device remembers for the user, each
 * one's preference, the templates (for the languages) and the user's consents (an opt-in needs
 * the channel's consent). A failed preference read is shown on its channel; a failed template
 * or consent read fails the page, since the forms depend on both.
 */
export interface NotificationQueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

export async function getNotificationSettings(
  session: ClientPrincipal,
  deps: NotificationQueryDeps = {},
): Promise<Result<NotificationSettingsView>> {
  const gateway = notificationPreferencesGateway({ session, fetchImpl: deps.fetchImpl });
  const recipients = await readRememberedRecipients(session.userId);
  const reads = CHANNELS.flatMap((channel): Promise<[Channel, PreferenceRead]>[] => {
    const recipient = recipients[channel];
    if (recipient === undefined) return [];
    return [gateway.preference(channel, recipient).then((read) => [channel, read])];
  });
  const [templates, consents, ...preferences] = await Promise.all([
    gateway.templates(),
    gateway.consents(session.userId),
    ...reads,
  ]);
  if (!templates.ok) return err(templates.error);
  if (!consents.ok) return err(consents.error);
  return ok(
    notificationSettingsView({
      recipients,
      preferences: Object.fromEntries(preferences),
      templates: templates.value,
      consents: consents.value,
    }),
  );
}
