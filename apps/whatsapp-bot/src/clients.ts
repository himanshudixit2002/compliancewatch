import type { PreferencesClient, QaClient, Sender } from "./conversation.ts";

type Fetch = typeof fetch;

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

  async setOptIn(phone: string, optedIn: boolean, language: "en" | "hi"): Promise<void> {
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
    this.log(
      `whatsapp-bot: send disabled; would reply to ${to.slice(-4).padStart(to.length, "*")}: ${body}`,
    );
  }
}

/** The qa service is not connected yet; every question gets the "not connected" reply. */
export class NotConnectedQa implements QaClient {
  async ask(): Promise<string | null> {
    return null;
  }
}
