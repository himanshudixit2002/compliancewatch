import type { ParsedWebhook } from "./webhook.ts";

/**
 * What the bot tells the notification service about a webhook delivery: the statuses Meta
 * reports for the messages the service sent (sent, delivered, read, failed), and when each
 * number wrote to the business, which opens WhatsApp's 24-hour customer service window. The
 * service matches the statuses to its notifications by Meta's message id; the statuses of the
 * bot's own replies match none and are ignored there.
 */
export interface StatusReport {
  readonly provider_message_id: string;
  readonly status: string;
  /** ISO 8601 in UTC, from Meta's Unix timestamp. */
  readonly at: string;
  readonly error_code?: number;
  readonly error_title?: string;
}

export interface InboundReport {
  /** The number as Meta sends it (919876543210); the service normalises it. */
  readonly address: string;
  readonly at: string;
}

export interface ReceiptsBody {
  readonly statuses: StatusReport[];
  readonly inbound: InboundReport[];
}

/** Where the reports go (the notification service); `forward` rejects when they did not. */
export interface ReceiptsClient {
  forward(body: ReceiptsBody): Promise<void>;
}

/** Meta's Unix timestamp in seconds as ISO 8601; null for anything else. */
export function isoFromUnix(timestamp: string): string | null {
  if (!/^\d{1,12}$/.test(timestamp)) return null;
  return new Date(Number(timestamp) * 1000).toISOString();
}

/**
 * The reports of one webhook delivery. A status without a message id or a readable time is
 * dropped, and each number that wrote is reported once, at its latest message.
 */
export function receiptsOf(parsed: ParsedWebhook): ReceiptsBody {
  const statuses: StatusReport[] = [];
  for (const update of parsed.statuses) {
    const at = isoFromUnix(update.timestamp);
    if (update.id === "" || update.status === "" || at === null) continue;
    statuses.push({
      provider_message_id: update.id,
      status: update.status,
      at,
      ...(update.errorCode === null ? {} : { error_code: update.errorCode }),
      ...(update.errorTitle === "" ? {} : { error_title: update.errorTitle }),
    });
  }
  const latest = new Map<string, string>();
  for (const message of parsed.messages) {
    const at = isoFromUnix(message.timestamp);
    if (message.from === "" || at === null) continue;
    const known = latest.get(message.from);
    if (known === undefined || at > known) latest.set(message.from, at);
  }
  const inbound = [...latest].map(([address, at]) => ({ address, at }));
  return { statuses, inbound };
}

export function isEmpty(body: ReceiptsBody): boolean {
  return body.statuses.length === 0 && body.inbound.length === 0;
}
