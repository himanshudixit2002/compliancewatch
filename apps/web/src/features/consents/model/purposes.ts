import { NOTICE_VERSION_MAX_LENGTH, type ConsentPurpose } from "@/entities/consent/types";
import type { LegalDocName } from "@/shared/config/legal-docs";
import { t } from "@/shared/i18n";

/**
 * The consent purposes the onboarding asks for, the legal document each one refers to, and the
 * words shown for them.
 *
 * Terms, privacy notice and profile processing are required: the service cannot work without
 * them. WhatsApp reminders, email reminders and product analytics are optional and unticked by
 * default. Each record carries `notice_version` as `<document>@<Version line>`
 * (`terms-of-service@0.1-draft`), naming the document as well as its version, because the
 * documents in docs/legal share version numbers. The checkbox wording is recorded as the
 * evidence, word for word; the WhatsApp wording is the one docs/legal/whatsapp-consent.md
 * publishes for the onboarding checkbox.
 */
export const REQUIRED_PURPOSES = [
  "terms",
  "privacy_notice",
  "profile_processing",
] as const satisfies readonly ConsentPurpose[];

export const OPTIONAL_PURPOSES = [
  "whatsapp_reminders",
  "email_reminders",
  "analytics",
] as const satisfies readonly ConsentPurpose[];

export type RequiredPurpose = (typeof REQUIRED_PURPOSES)[number];
export type OptionalPurpose = (typeof OPTIONAL_PURPOSES)[number];

/** Every onboarding purpose in the order it is asked and recorded. */
export const ONBOARDING_PURPOSES: readonly ConsentPurpose[] = [
  ...REQUIRED_PURPOSES,
  ...OPTIONAL_PURPOSES,
];

/** The document whose Version line a purpose's record carries. */
export const PURPOSE_DOCUMENT: Readonly<Record<ConsentPurpose, LegalDocName>> = {
  terms: "terms-of-service",
  privacy_notice: "privacy-notice",
  profile_processing: "privacy-notice",
  whatsapp_reminders: "whatsapp-consent",
  email_reminders: "privacy-notice",
  analytics: "privacy-notice",
};

/** What the page knows about a document: server/legal.ts's LegalVersion, structurally. */
export interface DocumentVersion {
  name: LegalDocName;
  title: string;
  version: string;
  isDraft: boolean;
}

export type DocumentVersions = Readonly<Record<LegalDocName, DocumentVersion>>;

export function isRequiredPurpose(purpose: ConsentPurpose): purpose is RequiredPurpose {
  return (REQUIRED_PURPOSES as readonly ConsentPurpose[]).includes(purpose);
}

/** "Terms of service", "WhatsApp reminders": the purpose's name in tables and summaries. */
export function purposeLabel(purpose: ConsentPurpose): string {
  return t(`consent.purpose.${purpose}`);
}

/** The sentence next to the purpose's checkbox, which a record keeps as its evidence. */
export function checkboxLabel(purpose: ConsentPurpose): string {
  return t(`consent.checkbox.${purpose}`);
}

/** `terms-of-service@0.1-draft`; throws when the service could not store it. */
export function noticeVersionOf(document: LegalDocName, version: string): string {
  const notice = `${document}@${version}`;
  if (notice.length > NOTICE_VERSION_MAX_LENGTH) {
    throw new Error(`notice version longer than ${NOTICE_VERSION_MAX_LENGTH}: ${notice}`);
  }
  return notice;
}

/** The notice version a record for this purpose carries, from the documents' Version lines. */
export function noticeFor(purpose: ConsentPurpose, versions: DocumentVersions): string {
  const document = PURPOSE_DOCUMENT[purpose];
  return noticeVersionOf(document, versions[document].version);
}
