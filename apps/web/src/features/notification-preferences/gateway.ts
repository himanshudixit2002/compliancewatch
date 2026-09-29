import "server-only";

import { consentSummaryFromDto } from "@/entities/consent/mappers";
import type { ConsentSummary } from "@/entities/consent/types";
import {
  preferenceChangeToDto,
  preferenceFromDto,
  templateFromDto,
} from "@/entities/notification/mappers";
import type {
  Channel,
  Preference,
  PreferenceChange,
  Template,
} from "@/entities/notification/types";
import { call } from "@/server/api/client";
import {
  identityClient,
  notificationClient,
  type ClientContext,
  type IdentityClient,
  type NotificationClient,
} from "@/server/api/services";
import { cachedRead, tags, uncachedRead } from "@/server/cache";
import { mapBody, ok, type Result } from "@/server/result";
import type { ConsentReadPort, NotificationPreferencesPort } from "./ports";

/**
 * Preferences and templates over the typed notification client, and the user's consents over
 * the typed identity client. A preference belongs to no tenant (the service ignores the tenant
 * header on these routes), so it is never cached: the page must show what was just saved. The
 * templates are the same for every tenant and are kept for five minutes under their tag. The
 * preference route answers 404 when nothing was ever recorded for the recipient; that is a
 * state of the page, so it becomes `null` here rather than an error.
 */
export class NotificationPreferencesGateway
  implements NotificationPreferencesPort, ConsentReadPort
{
  private readonly notification: NotificationClient;
  private readonly identity: IdentityClient;

  constructor(ctx: ClientContext) {
    this.notification = notificationClient(ctx);
    this.identity = identityClient(ctx);
  }

  async preference(channel: Channel, recipient: string): Promise<Result<Preference | null>> {
    const result = await call(
      this.notification.GET("/v1/notification/preferences/{channel}/{recipient}", {
        params: { path: { channel, recipient } },
        ...uncachedRead(),
      }),
    );
    if (!result.ok && result.error.kind === "not_found") return ok(null, result.error.requestId);
    return mapBody(result, preferenceFromDto);
  }

  async save(
    channel: Channel,
    recipient: string,
    change: PreferenceChange,
  ): Promise<Result<Preference>> {
    const result = await call(
      this.notification.PUT("/v1/notification/preferences/{channel}/{recipient}", {
        params: { path: { channel, recipient } },
        body: preferenceChangeToDto(change),
      }),
    );
    return mapBody(result, preferenceFromDto);
  }

  async templates(): Promise<Result<readonly Template[]>> {
    const result = await call(
      this.notification.GET("/v1/notification/templates", {
        ...cachedRead([tags.notification.templates()]),
      }),
    );
    return mapBody(result, (templates) => templates.map(templateFromDto));
  }

  async consents(subject: string): Promise<Result<ConsentSummary>> {
    const result = await call(
      this.identity.GET("/v1/identity/consents", {
        params: { query: { subject } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, consentSummaryFromDto);
  }
}

/** The gateway for a page or an action; tests add fetchImpl. */
export function notificationPreferencesGateway(ctx: ClientContext): NotificationPreferencesGateway {
  return new NotificationPreferencesGateway(ctx);
}
