import "server-only";

import type { ClientPrincipal, ClientContext } from "@/server/api/services";
import { readLegalVersions } from "@/server/legal";
import { mapResult, type Result } from "@/server/result";
import type { TenantKind } from "@/shared/config/roles";
import { consentsGateway } from "./gateway";
import { consentStepView, type ConsentStepView } from "./model/consent-step";

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
