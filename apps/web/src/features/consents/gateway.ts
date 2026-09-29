import "server-only";

import {
  consentRecordFromDto,
  consentSummaryFromDto,
  newConsentToDto,
} from "@/entities/consent/mappers";
import type { ConsentRecord, ConsentSummary, NewConsent } from "@/entities/consent/types";
import { preferenceChangeToDto, preferenceFromDto } from "@/entities/notification/mappers";
import type { Channel, Preference, PreferenceChange } from "@/entities/notification/types";
import { call } from "@/server/api/client";
import {
  identityClient,
  notificationClient,
  type ClientContext,
  type IdentityClient,
  type NotificationClient,
} from "@/server/api/services";
import { uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { ConsentsPort, ReminderPreferencePort } from "./ports";

/**
 * Consent records over the typed identity client and the reminder preference over the typed
 * notification client. Both carry the session's tenant as x-tenant-id (the notification
 * preference itself belongs to no tenant; the header is ignored there). Consent reads are never
 * cached: the step and the settings page must show the record just written.
 */
export class ConsentsGateway implements ConsentsPort, ReminderPreferencePort {
  private readonly identity: IdentityClient;
  private readonly notification: NotificationClient;

  constructor(ctx: ClientContext) {
    this.identity = identityClient(ctx);
    this.notification = notificationClient(ctx);
  }

  async summary(subject: string): Promise<Result<ConsentSummary>> {
    const result = await call(
      this.identity.GET("/v1/identity/consents", {
        params: { query: { subject } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, consentSummaryFromDto);
  }

  async record(input: NewConsent): Promise<Result<ConsentRecord>> {
    const result = await call(
      this.identity.POST("/v1/identity/consents", { body: newConsentToDto(input) }),
    );
    return mapBody(result, consentRecordFromDto);
  }

  async setPreference(
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
}

/** The gateway for a page or an action: `consentsGateway({ session })`; tests add fetchImpl. */
export function consentsGateway(ctx: ClientContext): ConsentsGateway {
  return new ConsentsGateway(ctx);
}
