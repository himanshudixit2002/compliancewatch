import "server-only";

import { consentSummaryFromDto, isGrantedAt } from "@/entities/consent/mappers";
import type { ConsentPurpose, ConsentSummary } from "@/entities/consent/types";
import type { LegalDocName } from "@/shared/config/legal-docs";
import { call, type FetchImpl } from "./api/client";
import { identityClient, type ClientPrincipal } from "./api/services";
import { uncachedRead } from "./cache";
import { readLegalVersions, type LegalVersion } from "./legal";
import { mapBody, mapResult, type Result } from "./result";

/**
 * The consents a person must have on file before a business profile is created or extended on
 * their behalf: the terms, the privacy notice and the processing of the business profile, each
 * granted at the Version line of its document this build ships (`<document>@<Version line>`,
 * D-026). The profile service does not check consents, so the web server does (D-028): the page
 * that offers a creating form checks before it renders the form, and the server action that
 * posts it checks again before any profile call, since an action can be invoked without the page
 * that rendered it.
 *
 * The purpose-to-document mapping is the consent step's (`PURPOSE_DOCUMENT` and
 * `REQUIRED_PURPOSES` in features/consents/model/purposes.ts, which a server module may not
 * import); that feature's test holds the two together.
 */
export const REQUIRED_CONSENT_DOCUMENTS = {
  terms: "terms-of-service",
  privacy_notice: "privacy-notice",
  profile_processing: "privacy-notice",
} as const satisfies Partial<Record<ConsentPurpose, LegalDocName>>;

export type RequiredConsent = keyof typeof REQUIRED_CONSENT_DOCUMENTS;

export const REQUIRED_CONSENTS = Object.keys(REQUIRED_CONSENT_DOCUMENTS) as RequiredConsent[];

type Versions = Readonly<Record<LegalDocName, LegalVersion>>;

/** True when the latest record of every required purpose grants it at its current version. */
export function requiredConsentsGranted(summary: ConsentSummary, versions: Versions): boolean {
  return REQUIRED_CONSENTS.every((purpose) => {
    const document = REQUIRED_CONSENT_DOCUMENTS[purpose];
    return isGrantedAt(summary, purpose, `${document}@${versions[document].version}`);
  });
}

/** The person's consent records (subject = the user id), never cached. */
export async function readConsentSummary(
  principal: ClientPrincipal,
  fetchImpl?: FetchImpl,
): Promise<Result<ConsentSummary>> {
  const client = identityClient({ session: principal, fetchImpl });
  const result = await call(
    client.GET("/v1/identity/consents", {
      params: { query: { subject: principal.userId } },
      ...uncachedRead(),
    }),
  );
  return mapBody(result, consentSummaryFromDto);
}

export interface RequiredConsentsDeps {
  fetchImpl?: FetchImpl;
  /** The documents' Version lines; read from docs/legal by default. */
  versions?: Versions;
}

/**
 * Whether the signed-in person has the required consents on file: true or false, or the
 * identity service's problem when the records cannot be read (a caller refuses then too).
 */
export async function hasRequiredConsents(
  principal: ClientPrincipal,
  deps: RequiredConsentsDeps = {},
): Promise<Result<boolean>> {
  const summary = await readConsentSummary(principal, deps.fetchImpl);
  if (!summary.ok) return summary;
  const versions = deps.versions ?? readLegalVersions();
  return mapResult(summary, (value) => requiredConsentsGranted(value, versions));
}
