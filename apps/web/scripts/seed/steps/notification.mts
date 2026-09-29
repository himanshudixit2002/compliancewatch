import { expectOk, type SeedClients } from "../http.mts";
import { DEMO } from "../lib.mts";

/**
 * The owner's WhatsApp preference on the notification service: opted in from the web
 * onboarding, Hindi, reminders held during the quiet hours, then read back.
 */
export interface NotificationResult {
  channel: "whatsapp";
  recipient: string;
  optedIn: boolean;
  language: string;
  quietHours: string;
}

export async function seedNotificationPreference(
  clients: SeedClients,
  log: (line: string) => void,
): Promise<NotificationResult> {
  const step = "notification";
  const path = { channel: "whatsapp" as const, recipient: DEMO.ownerPhone };
  await expectOk(
    step,
    "PUT /v1/notification/preferences/whatsapp/{recipient}",
    clients.notification.PUT("/v1/notification/preferences/{channel}/{recipient}", {
      params: { path },
      body: {
        opted_in: true,
        source: DEMO.consentSource,
        language: DEMO.whatsappLanguage,
        quiet_hours_start: DEMO.quietHours.start,
        quiet_hours_end: DEMO.quietHours.end,
      },
    }),
  );
  const stored = await expectOk(
    step,
    "GET /v1/notification/preferences/whatsapp/{recipient}",
    clients.notification.GET("/v1/notification/preferences/{channel}/{recipient}", {
      params: { path },
    }),
  );
  const result: NotificationResult = {
    channel: "whatsapp",
    recipient: stored.data.recipient,
    optedIn: stored.data.opted_in,
    language: stored.data.language,
    quietHours: `${stored.data.quiet_hours_start}-${stored.data.quiet_hours_end}`,
  };
  log(
    `notification: whatsapp ${result.recipient} ${result.optedIn ? "opted in" : "NOT opted in"},` +
      ` language ${result.language}, quiet hours ${result.quietHours}`,
  );
  return result;
}
