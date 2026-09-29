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

export function isLegalDoc(value: string): value is LegalDocName {
  return (LEGAL_DOC_NAMES as readonly string[]).includes(value);
}

export function legalDocTitle(name: LegalDocName): string {
  const doc = LEGAL_DOCS.find((entry) => entry.name === name);
  if (doc === undefined) throw new Error(`unknown legal document: ${name}`);
  return doc.title;
}
