import "server-only";

import {
  messageTemplateFromDto,
  notificationFromDto,
  notificationPageFromDto,
} from "@/entities/notification/mappers";
import type {
  DeliveryState,
  MessageTemplate,
  NotificationPage,
  NotificationRecord,
} from "@/entities/notification/types";
import { call } from "@/server/api/client";
import {
  notificationClient,
  profileClient,
  type ClientContext,
  type NotificationClient,
  type ProfileClient,
} from "@/server/api/services";
import { cachedRead, tags, uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { BusinessRef } from "./model/history";
import type { BusinessNamePort, NotificationHistoryPort, TemplatesPort } from "./ports";

/**
 * The notification history over the typed notification client, and the business it is about over
 * the typed profile client. Both are tenant data: every call carries x-tenant-id (the session's,
 * or for an admin lookup the tenant the lookup names, `ctx.tenantId`) and is never cached, since
 * delivery moves on.
 */
export class NotificationsGateway
  implements NotificationHistoryPort, BusinessNamePort, TemplatesPort
{
  private readonly notification: NotificationClient;
  private readonly profile: ProfileClient;

  constructor(ctx: ClientContext) {
    this.notification = notificationClient(ctx);
    this.profile = profileClient(ctx);
  }

  async page(
    businessId: string,
    query: { state?: DeliveryState; cursor?: string; limit: number },
  ): Promise<Result<NotificationPage>> {
    const result = await call(
      this.notification.GET("/v1/notification/notifications", {
        params: {
          query: {
            business_id: businessId,
            limit: query.limit,
            ...(query.state === undefined ? {} : { state: query.state }),
            ...(query.cursor === undefined ? {} : { cursor: query.cursor }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, notificationPageFromDto);
  }

  async get(notificationId: string): Promise<Result<NotificationRecord>> {
    const result = await call(
      this.notification.GET("/v1/notification/notifications/{notification_id}", {
        params: { path: { notification_id: notificationId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, notificationFromDto);
  }

  /** The templates are the same for every tenant: kept five minutes under their tag. */
  async templates(): Promise<Result<readonly MessageTemplate[]>> {
    const result = await call(
      this.notification.GET("/v1/notification/templates", {
        ...cachedRead([tags.notification.templates()]),
      }),
    );
    return mapBody(result, (templates) => templates.map(messageTemplateFromDto));
  }

  async business(businessId: string): Promise<Result<BusinessRef>> {
    const result = await call(
      this.profile.GET("/v1/businesses/{business_id}", {
        params: { path: { business_id: businessId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (business) => ({
      id: business.id,
      name: business.name,
      pan: business.pan,
    }));
  }
}

/** The gateway for a page; tests add fetchImpl, an admin lookup the tenant it reads for. */
export function notificationsGateway(ctx: ClientContext): NotificationsGateway {
  return new NotificationsGateway(ctx);
}
