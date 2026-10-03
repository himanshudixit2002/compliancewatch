import type { NotificationSummary } from "@/features/notifications/model/notifications";

export interface NotificationDetailViewProps {
  notification: NotificationSummary;
  listHref: string;
}
