/**
 * The Cloud API webhook payload mapped to the few things the bot acts on. Vendor shapes stop
 * here (guide section 11, anti-corruption layer); everything inward is `InboundMessage`.
 */
export interface InboundMessage {
  readonly id: string;
  readonly from: string;
  readonly timestamp: string;
  readonly text: string | null;
  readonly type: string;
  readonly phoneNumberId: string;
}

export interface StatusUpdate {
  readonly id: string;
  readonly recipient: string;
  readonly status: string;
  readonly timestamp: string;
  /** The code of the first error Meta gave a failed status; null when it gave none. */
  readonly errorCode: number | null;
  /** The title of that error ("Message undeliverable"); empty when it gave none. */
  readonly errorTitle: string;
}

export interface ParsedWebhook {
  readonly messages: InboundMessage[];
  readonly statuses: StatusUpdate[];
}

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function parseWebhook(payload: unknown): ParsedWebhook {
  const messages: InboundMessage[] = [];
  const statuses: StatusUpdate[] = [];
  if (!isObject(payload) || payload.object !== "whatsapp_business_account") {
    return { messages, statuses };
  }
  const entries = Array.isArray(payload.entry) ? payload.entry : [];
  for (const entry of entries) {
    if (!isObject(entry)) continue;
    const changes = Array.isArray(entry.changes) ? entry.changes : [];
    for (const change of changes) {
      if (!isObject(change) || !isObject(change.value)) continue;
      const value = change.value;
      const metadata = isObject(value.metadata) ? value.metadata : {};
      const phoneNumberId = str(metadata.phone_number_id);
      for (const message of Array.isArray(value.messages) ? value.messages : []) {
        if (!isObject(message)) continue;
        const text = isObject(message.text) ? str(message.text.body) : "";
        messages.push({
          id: str(message.id),
          from: str(message.from),
          timestamp: str(message.timestamp),
          text: text === "" ? null : text,
          type: str(message.type),
          phoneNumberId,
        });
      }
      for (const status of Array.isArray(value.statuses) ? value.statuses : []) {
        if (!isObject(status)) continue;
        const errors = Array.isArray(status.errors) ? status.errors : [];
        const error: Json = isObject(errors[0]) ? errors[0] : {};
        statuses.push({
          id: str(status.id),
          recipient: str(status.recipient_id),
          status: str(status.status),
          timestamp: str(status.timestamp),
          errorCode: Number.isInteger(error.code) ? (error.code as number) : null,
          errorTitle: str(error.title),
        });
      }
    }
  }
  return { messages, statuses };
}
