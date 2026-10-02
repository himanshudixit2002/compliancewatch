/**
 * Notifications model: types and server query stubs for the notifications list and detail
 * screens. Queries return { ok: true, value: T } or { ok: false, error: { kind, message } }.
 */

export interface NotificationView {
  id: string;
  subject: string;
  channel: "email" | "whatsapp";
  status: "sent" | "delivered" | "read" | "failed";
  recipient: string;
  sentAt: string;
  readAt: string | null;
  templateKey: string;
}

export interface NotificationDetailView extends NotificationView {
  body: string;
  tenantName: string | null;
  deliveryAttempts: number;
  errorMessage: string | null;
}

export async function notifications(): Promise<
  { ok: true; value: NotificationView[] } | { ok: false; error: { kind: string; message: string } }
> {
  // TODO: call notification service GET /v1/notification/notifications
  return { ok: true, value: [] };
}

export async function notificationById(
  id: string,
): Promise<
  { ok: true; value: NotificationDetailView } | { ok: false; error: { kind: string; message: string } }
> {
  // TODO: call notification service GET /v1/notification/notifications/{id}
  return { ok: false, error: { kind: "not_found", message: "Notification not found" } };
}
