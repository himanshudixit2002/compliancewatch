import { isGrantedAt, stateOf } from "@/entities/consent/mappers";
import type { ConsentPurpose, ConsentSummary } from "@/entities/consent/types";
import { LEGAL_DOC_NAMES, type LegalDocName } from "@/shared/config/legal-docs";
import type { TenantKind } from "@/shared/config/roles";
import { formatDateTime } from "@/shared/lib/dates";
import {
  ONBOARDING_PURPOSES,
  PURPOSE_DOCUMENT,
  REQUIRED_PURPOSES,
  checkboxLabel,
  isRequiredPurpose,
  noticeFor,
  purposeLabel,
  type DocumentVersion,
  type DocumentVersions,
} from "./purposes";

/**
 * What the consent step shows, from the user's consent records and the documents' current
 * versions:
 *
 * - `accepted`: every required purpose is granted at the notice version this build ships, so
 *   the step shows what was agreed and a way on instead of the form;
 * - `options`: the checkboxes, required first, each with its wording, the document it refers to
 *   and whether it is already granted at the current version;
 * - `drafts`: the documents still marked -draft, which the page names under the draft banner.
 *
 * A CA firm gets no WhatsApp box: reminders are set for each client business, not the firm.
 */
export interface ConsentOption {
  purpose: ConsentPurpose;
  /** The checkbox sentence; recorded as the evidence. */
  label: string;
  required: boolean;
  document: DocumentVersion;
  noticeVersion: string;
  /** Granted at the current version already; the box starts ticked. */
  granted: boolean;
}

export interface AcceptedPurpose {
  purpose: ConsentPurpose;
  label: string;
  noticeVersion: string;
  /** When the current record was written, in IST. */
  recordedAt: string;
}

export interface ConsentStepView {
  accepted: boolean;
  acceptedPurposes: readonly AcceptedPurpose[];
  options: readonly ConsentOption[];
  /** True when the WhatsApp box is offered (business tenants). */
  offerWhatsapp: boolean;
  drafts: readonly DocumentVersion[];
}

/** The purposes a tenant kind is asked for, in order. */
export function purposesFor(tenantKind: TenantKind): readonly ConsentPurpose[] {
  return tenantKind === "business"
    ? ONBOARDING_PURPOSES
    : ONBOARDING_PURPOSES.filter((purpose) => purpose !== "whatsapp_reminders");
}

/** True when every required purpose is granted at the notice version this build ships. */
export function hasAcceptedRequired(summary: ConsentSummary, versions: DocumentVersions): boolean {
  return REQUIRED_PURPOSES.every((purpose) =>
    isGrantedAt(summary, purpose, noticeFor(purpose, versions)),
  );
}

/** The documents the step refers to that are still drafts, in docs/legal order. */
export function draftDocuments(
  purposes: readonly ConsentPurpose[],
  versions: DocumentVersions,
): DocumentVersion[] {
  const used = new Set<LegalDocName>(purposes.map((purpose) => PURPOSE_DOCUMENT[purpose]));
  return LEGAL_DOC_NAMES.filter((name) => used.has(name))
    .map((name) => versions[name])
    .filter((document) => document.isDraft);
}

export function consentStepView(
  summary: ConsentSummary,
  versions: DocumentVersions,
  tenantKind: TenantKind,
): ConsentStepView {
  const purposes = purposesFor(tenantKind);
  const options = purposes.map((purpose): ConsentOption => {
    const noticeVersion = noticeFor(purpose, versions);
    return {
      purpose,
      label: checkboxLabel(purpose),
      required: isRequiredPurpose(purpose),
      document: versions[PURPOSE_DOCUMENT[purpose]],
      noticeVersion,
      granted: isGrantedAt(summary, purpose, noticeVersion),
    };
  });
  const acceptedPurposes = options.flatMap((option): AcceptedPurpose[] => {
    const state = stateOf(summary, option.purpose);
    if (!option.granted || state === undefined) return [];
    return [
      {
        purpose: option.purpose,
        label: purposeLabel(option.purpose),
        noticeVersion: option.noticeVersion,
        recordedAt: formatDateTime(state.since),
      },
    ];
  });
  return {
    accepted: hasAcceptedRequired(summary, versions),
    acceptedPurposes,
    options,
    offerWhatsapp: purposes.includes("whatsapp_reminders"),
    drafts: draftDocuments(purposes, versions),
  };
}

/**
 * The chosen purposes that still need a record: those not already granted at the current
 * notice version, in the order they are asked. A retry after a partial failure therefore
 * records only what is missing, and an agreement already on file is not written twice.
 */
export function purposesToRecord(
  chosen: readonly ConsentPurpose[],
  summary: ConsentSummary,
  versions: DocumentVersions,
): ConsentPurpose[] {
  return ONBOARDING_PURPOSES.filter(
    (purpose) =>
      chosen.includes(purpose) && !isGrantedAt(summary, purpose, noticeFor(purpose, versions)),
  );
}
