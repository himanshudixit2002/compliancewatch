/**
 * The legal documents rendered from docs/legal at /legal/[doc]. The names are the file stems
 * under docs/legal; the titles are shown in links, and the document's own heading is the page
 * title. server/legal.ts reads the files; this list stays isomorphic so links can be built
 * anywhere.
 */
export const LEGAL_DOCS = [
  { name: "privacy-notice", title: "Privacy notice" },
  { name: "terms-of-service", title: "Terms of service" },
  { name: "whatsapp-consent", title: "WhatsApp consent" },
] as const;

export type LegalDocName = (typeof LEGAL_DOCS)[number]["name"];

export const LEGAL_DOC_NAMES: readonly LegalDocName[] = LEGAL_DOCS.map((doc) => doc.name);

/**
 * The documents every customer agrees to before anything else: the ones the required consent
 * purposes refer to (the terms, and the privacy notice for the privacy notice and profile
 * processing purposes; features/consents maps each purpose to its document, and its test holds
 * the two lists together). While one of these is a draft, production onboarding is closed
 * (server/legal.ts, onboardingGate). The WhatsApp consent notice covers an optional purpose.
 */
export const REQUIRED_LEGAL_DOCS: readonly LegalDocName[] = ["privacy-notice", "terms-of-service"];

export function isLegalDoc(value: string): value is LegalDocName {
  return (LEGAL_DOC_NAMES as readonly string[]).includes(value);
}

export function legalDocTitle(name: LegalDocName): string {
  const doc = LEGAL_DOCS.find((entry) => entry.name === name);
  if (doc === undefined) throw new Error(`unknown legal document: ${name}`);
  return doc.title;
}
