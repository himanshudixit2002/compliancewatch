import { randomUUID } from "node:crypto";
import { SeedError, expectOk, type SeedClients } from "../http.mts";
import { DEMO, NO_OBLIGATION } from "../lib.mts";

/**
 * The owner's WhatsApp preference on the notification service (opted in from the web onboarding,
 * Hindi, reminders held during the quiet hours), read back; then one notification for the demo
 * business, so the reminders pages have a real record to show: the opt-in confirmation sent to
 * that number through `POST /v1/notification/send`, the route that sends one notification now
 * (dedupe, consent, quiet hours, queue, deliver). Nothing else on the web stack creates a
 * notification: the obligation events that queue reminders need the workers. The route needs an
 * obligation id and the confirmation is about none, so the seed names the nil UUID.
 *
 * On the web stack the WhatsApp channel is not wired, so the service records the notification as
 * queued with its failed first attempt and the reason, to be tried again by a worker the stack
 * does not run; inside the quiet hours it is queued, untried, for their end. A repeat run on the
 * same tenant is answered as a duplicate and records nothing new. The business's history is read
 * back, and an empty one fails the step.
 */
export interface NotificationResult {
  channel: "whatsapp";
  recipient: string;
  optedIn: boolean;
  language: string;
  quietHours: string;
  confirmation: {
    /** The service's outcome: sent, failed (retried later), deferred, duplicate, not_opted_in. */
    outcome: string;
    /** The channel's error for a failed attempt; empty otherwise. */
    error: string;
  };
  /** The business's notifications as the service lists them, with their states. */
  history: { total: number; states: string[] };
}

export async function seedNotification(
  clients: SeedClients,
  businessId: string,
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
  const sent = await expectOk(
    step,
    "POST /v1/notification/send",
    clients.notification.POST("/v1/notification/send", {
      body: {
        notification_id: randomUUID(),
        obligation_id: NO_OBLIGATION,
        business_id: businessId,
        channel: "whatsapp",
        recipient: DEMO.ownerPhone,
        template_key: DEMO.confirmationTemplate,
      },
    }),
  );
  const listed = await expectOk(
    step,
    "GET /v1/notification/notifications",
    clients.notification.GET("/v1/notification/notifications", {
      params: { query: { business_id: businessId } },
    }),
  );
  if (listed.data.items.length === 0) {
    throw new SeedError({
      step,
      request: "GET /v1/notification/notifications",
      title: "the business has no notification after the send",
      detail: `the send answered ${sent.data.outcome}`,
    });
  }
  const result: NotificationResult = {
    channel: "whatsapp",
    recipient: stored.data.recipient,
    optedIn: stored.data.opted_in,
    language: stored.data.language,
    quietHours: `${stored.data.quiet_hours_start}-${stored.data.quiet_hours_end}`,
    confirmation: { outcome: sent.data.outcome, error: sent.data.error ?? "" },
    history: {
      total: listed.data.items.length,
      states: listed.data.items.map((item) => item.state),
    },
  };
  log(
    `notification: whatsapp ${result.recipient} ${result.optedIn ? "opted in" : "NOT opted in"},` +
      ` language ${result.language}, quiet hours ${result.quietHours}`,
  );
  log(
    `notification: opt-in confirmation ${result.confirmation.outcome}` +
      (result.confirmation.error === "" ? "" : ` (${result.confirmation.error})`) +
      `; ${result.history.total} notification(s) for the business: ${result.history.states.join(", ")}`,
  );
  return result;
}
