import type { ConsentLedger, PreferencesClient, QaClient, Sender } from "./conversation.ts";
import { maskNumber } from "./conversation.ts";
import type { ReceiptsBody, ReceiptsClient } from "./receipts.ts";
import type { Language } from "./replies.ts";

type Fetch = typeof fetch;

/** The version line of docs/legal/whatsapp-consent.md: the notice a keyword opt-in agrees to. */
export const DEFAULT_NOTICE_VERSION = "whatsapp-consent 0.1-draft";
export const DEFAULT_IDENTITY_API_URL = "http://localhost:8001";
export const DEFAULT_NOTIFICATION_API_URL = "http://localhost:8006";

/** The notification service's preference endpoints; recipient is the E.164 number. */
export class HttpPreferencesClient implements PreferencesClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: Fetch;

  constructor(baseUrl: string, fetchImpl: Fetch = fetch) {
    this.baseUrl = baseUrl;
    this.fetchImpl = fetchImpl;
  }

  private url(phone: string): string {
    return `${this.baseUrl.replace(/\/$/, "")}/v1/notification/preferences/whatsapp/${encodeURIComponent(phone)}`;
  }

  async setOptIn(phone: string, optedIn: boolean, language: Language): Promise<void> {
    const res = await this.fetchImpl(this.url(phone), {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ opted_in: optedIn, source: "whatsapp_keyword", language }),
    });
    if (!res.ok) throw new Error(`preferences: ${res.status}`);
  }

  async isOptedIn(phone: string): Promise<boolean> {
    const res = await this.fetchImpl(this.url(phone));
    if (res.status === 404) return false;
    if (!res.ok) throw new Error(`preferences: ${res.status}`);
    const body = (await res.json()) as { opted_in?: unknown };
    return body.opted_in === true;
  }
}

/**
 * The notification service's receipt route: the statuses and inbound times of a webhook delivery,
 * with the bot's shared token (NOTIFICATION_BOT_TOKEN here, CW_NOTIFICATION_BOT_TOKEN there).
 */
export class HttpReceiptsClient implements ReceiptsClient {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly fetchImpl: Fetch;

  constructor(baseUrl: string, token: string, fetchImpl: Fetch = fetch) {
    this.baseUrl = baseUrl;
    this.token = token;
    this.fetchImpl = fetchImpl;
  }

  async forward(body: ReceiptsBody): Promise<void> {
    const res = await this.fetchImpl(
      `${this.baseUrl.replace(/\/$/, "")}/v1/notification/receipts/whatsapp`,
      {
        method: "POST",
        headers: { "content-type": "application/json", "x-cw-bot-token": this.token },
        body: JSON.stringify(body),
      },
    );
    if (!res.ok) throw new Error(`receipts: ${res.status}`);
  }
}

/** What runs without NOTIFICATION_BOT_TOKEN: nothing is forwarded. */
export class NoReceiptsForwarding implements ReceiptsClient {
  async forward(): Promise<void> {}
}

/**
 * The receipts client the environment allows. Without NOTIFICATION_BOT_TOKEN the bot still runs,
 * but warns once that delivery statuses and inbound times stay with it: the notification
 * service then never sees a message delivered, and treats every number as outside the 24-hour
 * window.
 */
export function receiptsClient(
  env: Readonly<Record<string, string | undefined>>,
  fetchImpl: Fetch = fetch,
  warn: (line: string) => void = console.warn,
): ReceiptsClient {
  const token = env.NOTIFICATION_BOT_TOKEN ?? "";
  if (token === "") {
    warn(
      "whatsapp-bot: NOTIFICATION_BOT_TOKEN is not set; delivery statuses and inbound times are not forwarded to notification",
    );
    return new NoReceiptsForwarding();
  }
  return new HttpReceiptsClient(
    env.NOTIFICATION_API_URL || DEFAULT_NOTIFICATION_API_URL,
    token,
    fetchImpl,
  );
}

/**
 * The identity service's channel consents: every keyword opt-in or opt-out becomes a consent
 * record keyed by the number, with the message as evidence. Identity refuses the call without
 * the shared service token (CW_IDENTITY_CHANNEL_TOKEN there, IDENTITY_SERVICE_TOKEN here).
 */
export class HttpConsentLedger implements ConsentLedger {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly noticeVersion: string;
  private readonly fetchImpl: Fetch;
  private readonly now: () => Date;

  constructor(
    baseUrl: string,
    token: string,
    noticeVersion = DEFAULT_NOTICE_VERSION,
    fetchImpl: Fetch = fetch,
    now: () => Date = () => new Date(),
  ) {
    this.baseUrl = baseUrl;
    this.token = token;
    this.noticeVersion = noticeVersion;
    this.fetchImpl = fetchImpl;
    this.now = now;
  }

  async record(
    phone: string,
    granted: boolean,
    keyword: string,
    messageId: string,
    language: Language,
  ): Promise<void> {
    const at = this.now().toISOString();
    const res = await this.fetchImpl(
      `${this.baseUrl.replace(/\/$/, "")}/v1/identity/channel-consents`,
      {
        method: "POST",
        headers: { "content-type": "application/json", "x-cw-service-token": this.token },
        body: JSON.stringify({
          channel: "whatsapp",
          subject: phone,
          purpose: "whatsapp_reminders",
          granted,
          source: "whatsapp_keyword",
          notice_version: this.noticeVersion,
          evidence: `keyword ${keyword} in WhatsApp message ${messageId} at ${at}, language ${language}`,
          message_id: messageId,
        }),
      },
    );
    if (!res.ok) throw new Error(`consents: ${res.status}`);
  }
}

/** What runs while WHATSAPP_CONSENT_RECORDING_ENABLED is off: the consent is logged, not sent. */
export class NoConsentLedger implements ConsentLedger {
  private readonly log: (line: string) => void;

  constructor(log: (line: string) => void = console.log) {
    this.log = log;
  }

  async record(phone: string, granted: boolean, keyword: string, messageId: string): Promise<void> {
    this.log(
      `whatsapp-bot: consent recording disabled; would record the ${granted ? "opt-in" : "opt-out"} of ${maskNumber(phone)} (keyword ${keyword}, message ${messageId})`,
    );
  }
}

/**
 * The ledger the environment asks for. WHATSAPP_CONSENT_RECORDING_ENABLED is off by default
 * (owner core-product; removed once the lawyer confirms keyword opt-in is valid consent). On,
 * it needs IDENTITY_SERVICE_TOKEN, and the bot refuses to start without it rather than switch
 * reminders on with no record.
 */
export function consentLedger(
  env: Readonly<Record<string, string | undefined>>,
  fetchImpl: Fetch = fetch,
  log: (line: string) => void = console.log,
): ConsentLedger {
  if (env.WHATSAPP_CONSENT_RECORDING_ENABLED !== "true") return new NoConsentLedger(log);
  const token = env.IDENTITY_SERVICE_TOKEN ?? "";
  if (token === "") {
    throw new Error("WHATSAPP_CONSENT_RECORDING_ENABLED=true needs IDENTITY_SERVICE_TOKEN");
  }
  return new HttpConsentLedger(
    env.IDENTITY_API_URL || DEFAULT_IDENTITY_API_URL,
    token,
    env.WHATSAPP_NOTICE_VERSION || DEFAULT_NOTICE_VERSION,
    fetchImpl,
  );
}

/** Sends through the Cloud API. Only wired when WHATSAPP_SEND_ENABLED=true and credentials exist. */
export class CloudApiSender implements Sender {
  private readonly phoneNumberId: string;
  private readonly accessToken: string;
  private readonly apiVersion: string;
  private readonly fetchImpl: Fetch;

  constructor(
    phoneNumberId: string,
    accessToken: string,
    apiVersion = "v21.0",
    fetchImpl: Fetch = fetch,
  ) {
    this.phoneNumberId = phoneNumberId;
    this.accessToken = accessToken;
    this.apiVersion = apiVersion;
    this.fetchImpl = fetchImpl;
  }

  async sendText(to: string, body: string): Promise<void> {
    const res = await this.fetchImpl(
      `https://graph.facebook.com/${this.apiVersion}/${this.phoneNumberId}/messages`,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${this.accessToken}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({
          messaging_product: "whatsapp",
          recipient_type: "individual",
          to,
          type: "text",
          text: { preview_url: false, body },
        }),
      },
    );
    if (!res.ok) throw new Error(`cloud api: ${res.status} ${await res.text()}`);
  }
}

/** What runs while sending is off: the reply is logged, nothing leaves the process. */
export class LoggingSender implements Sender {
  readonly sent: Array<{ to: string; body: string }> = [];
  private readonly log: (line: string) => void;

  constructor(log: (line: string) => void = console.log) {
    this.log = log;
  }

  async sendText(to: string, body: string): Promise<void> {
    this.sent.push({ to, body });
    this.log(`whatsapp-bot: send disabled; would reply to ${maskNumber(to)}: ${body}`);
  }
}

/** The qa service is not connected yet; every question gets the "not connected" reply. */
export class NotConnectedQa implements QaClient {
  async ask(): Promise<string | null> {
    return null;
  }
}
