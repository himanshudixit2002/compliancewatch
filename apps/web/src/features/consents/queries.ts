import "server-only";

import { whatsappNumberOf } from "@/entities/notification/mappers";
import type { ClientPrincipal, ClientContext } from "@/server/api/services";
import { readLegalVersions } from "@/server/legal";
import { readRememberedRecipients } from "@/server/remembered-recipients";
import { mapResult, type Result } from "@/server/result";
import type { TenantKind } from "@/shared/config/roles";
import { consentsGateway } from "./gateway";
import { consentStepView, type ConsentStepView } from "./model/consent-step";
import { consentSettingsView, type ConsentSettingsView } from "./model/settings";

/**
 * The consent step's read: the signed-in user's consent records (subject = the user id) and
 * the Version lines of docs/legal as this build ships them.
 */
export interface ConsentQueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
  /** docs/legal, for tests; the default finds it from the working directory. */
  legalDir?: string;
}

export interface ConsentSession extends ClientPrincipal {
  tenantKind: TenantKind;
}

export async function getConsentStep(
  session: ConsentSession,
  deps: ConsentQueryDeps = {},
): Promise<Result<ConsentStepView>> {
  const versions = readLegalVersions(deps.legalDir);
  const summary = await consentsGateway({ session, fetchImpl: deps.fetchImpl }).summary(
    session.userId,
  );
  return mapResult(summary, (value) => consentStepView(value, versions, session.tenantKind));
}

/**
 * The consents settings page's read: the user's records, the documents' Version lines, and the
 * WhatsApp number this device remembers for the user (to fill the withdraw and give dialogs).
 */
export async function getConsentSettings(
  session: ConsentSession,
  deps: ConsentQueryDeps = {},
): Promise<Result<ConsentSettingsView>> {
  const versions = readLegalVersions(deps.legalDir);
  const [summary, remembered] = await Promise.all([
    consentsGateway({ session, fetchImpl: deps.fetchImpl }).summary(session.userId),
    readRememberedRecipients(session.userId),
  ]);
  return mapResult(summary, (value) =>
    consentSettingsView(value, versions, {
      tenantKind: session.tenantKind,
      userId: session.userId,
      whatsappNumber:
        remembered.whatsapp === undefined ? "" : whatsappNumberOf(remembered.whatsapp),
    }),
  );
}
