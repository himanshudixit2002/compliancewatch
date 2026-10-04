import "server-only";

import { businessPageFromDto } from "@/entities/business/mappers";
import type { BusinessPage } from "@/entities/business/types";
import {
  recipientFromDto,
  recipientInputToDto,
  recipientPageFromDto,
  templateFromDto,
} from "@/entities/notification/mappers";
import type {
  Recipient,
  RecipientInput,
  RecipientPage,
  Template,
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
import { mapBody, mapResult, type Result } from "@/server/result";
import type { BusinessChoicePort, RecipientsPort } from "./ports";

/**
 * The recipient routes over the typed notification client, and the tenant's businesses over the
 * typed profile client. Recipients and businesses are tenant data (x-tenant-id from the session,
 * never cached); the templates are the same for every tenant and are kept for five minutes under
 * `notification:templates`. A PUT replaces the recipient whole, so the action sends everything.
 */
export class RecipientsGateway implements RecipientsPort, BusinessChoicePort {
  private readonly notification: NotificationClient;
  private readonly profile: ProfileClient;

  constructor(ctx: ClientContext) {
    this.notification = notificationClient(ctx);
    this.profile = profileClient(ctx);
  }

  async list(businessId: string, limit: number): Promise<Result<RecipientPage>> {
    const result = await call(
      this.notification.GET("/v1/notification/recipients", {
        params: { query: { business_id: businessId, limit } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, recipientPageFromDto);
  }

  async get(recipientId: string): Promise<Result<Recipient>> {
    const result = await call(
      this.notification.GET("/v1/notification/recipients/{recipient_id}", {
        params: { path: { recipient_id: recipientId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, recipientFromDto);
  }

  async put(recipientId: string, input: RecipientInput): Promise<Result<Recipient>> {
    const result = await call(
      this.notification.PUT("/v1/notification/recipients/{recipient_id}", {
        params: { path: { recipient_id: recipientId } },
        body: recipientInputToDto(input),
      }),
    );
    return mapBody(result, recipientFromDto);
  }

  async remove(recipientId: string): Promise<Result<void>> {
    const result = await call(
      this.notification.DELETE("/v1/notification/recipients/{recipient_id}", {
        params: { path: { recipient_id: recipientId } },
      }),
    );
    return mapResult(result, () => undefined);
  }

  async templates(): Promise<Result<readonly Template[]>> {
    const result = await call(
      this.notification.GET("/v1/notification/templates", {
        ...cachedRead([tags.notification.templates()]),
      }),
    );
    return mapBody(result, (templates) => templates.map(templateFromDto));
  }

  async businesses(limit: number): Promise<Result<BusinessPage>> {
    const result = await call(
      this.profile.GET("/v1/businesses", { params: { query: { limit } }, ...uncachedRead() }),
    );
    return mapBody(result, businessPageFromDto);
  }
}

/** The gateway for a page or an action; tests add fetchImpl. */
export function recipientsGateway(ctx: ClientContext): RecipientsGateway {
  return new RecipientsGateway(ctx);
}
