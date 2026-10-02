/**
 * Reminders model: types and server query stub for the reminders timeline screen.
 */

export interface ReminderView {
  id: string;
  title: string;
  description: string;
  dueAt: string;
  status: "upcoming" | "sent" | "acknowledged" | "overdue";
  channel: "email" | "whatsapp";
  obligationId: string | null;
  createdAt: string;
}

export async function reminders(): Promise<
  { ok: true; value: ReminderView[] } | { ok: false; error: { kind: string; message: string } }
> {
  // TODO: call notification service for upcoming reminders
  return { ok: true, value: [] };
}
