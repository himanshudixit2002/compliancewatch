/**
 * Notification recipients model: types and server query stub.
 */

export interface RecipientView {
  id: string;
  channel: "email" | "whatsapp";
  address: string;
  optedIn: boolean;
  language: string;
  quietHoursStart: string;
  quietHoursEnd: string;
  updatedAt: string;
  source: string;
}

export async function recipients(): Promise<
  { ok: true; value: RecipientView[] } | { ok: false; error: { kind: string; message: string } }
> {
  // TODO: call notification service GET /v1/notification/recipients
  return { ok: true, value: [] };
}
