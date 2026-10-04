import type {
  DeliveryState,
  NotificationPage,
  NotificationRecord,
} from "@/entities/notification/types";
import type { Result } from "@/server/result";
import type { BusinessRef } from "./model/history";

/**
 * What the notification history needs: a business's notifications, newest first, a page at a
 * time, and one notification, both for the tenant the gateway acts for.
 */
export interface NotificationHistoryPort {
  page(
    businessId: string,
    query: { state?: DeliveryState; cursor?: string; limit: number },
  ): Promise<Result<NotificationPage>>;
  get(notificationId: string): Promise<Result<NotificationRecord>>;
}

/** And the business the history is about, to name it and to check the tenant holds it. */
export interface BusinessNamePort {
  business(businessId: string): Promise<Result<BusinessRef>>;
}
