import type { BusinessSummary } from "@/entities/business/types";
import type {
  DigestMode,
  Recipient,
  RecipientAddress,
  RecipientRole,
  Template,
} from "@/entities/notification/types";
import type { TenantKind } from "@/shared/config/roles";
import { t } from "@/shared/i18n";
import { DEFAULT_LANGUAGE, languageName, languageOptions } from "@/shared/lib/languages";
import type { LanguageOption } from "@/shared/lib/languages";
import { withQuery } from "@/shared/lib/url";
import { MAX_ADDRESSES } from "./recipient-form";
import {
  CHANNEL_LABEL,
  DIGEST_LABEL,
  ROLE_LABEL,
  recipientSummary,
  rolesFor,
  sortRecipients,
  type RecipientSummary,
} from "./recipients";

/**
 * The recipients page as it renders: the tenant's businesses to choose from, the recipients that
 * follow the chosen one, and the form, empty for a new recipient or filled for the one being
 * changed. A new recipient's id is minted for the render, so submitting the same form twice
 * replaces one recipient rather than adding two (`PUT` by id is a replacement).
 */
export const BUSINESS_CHOICES = 200;
export const RECIPIENTS_PAGE_SIZE = 200;

export interface BusinessChoice {
  id: string;
  name: string;
}

export interface Option {
  value: string;
  label: string;
}

export interface RecipientRow {
  id: string;
  orgLabel: string;
  roleLabel: string;
  addresses: { channel: string; channelLabel: string; address: string }[];
  /** The businesses it follows, named by the tenant's business list or the recipient's label. */
  businesses: string[];
  languageLabel: string;
  deliveryLabel: string;
  updatedAt: string;
  editHref: string;
}

export interface RecipientFormValues {
  role: RecipientRole;
  language: string;
  digestMode: DigestMode;
  orgLabel: string;
  addresses: readonly RecipientAddress[];
  businessIds: readonly string[];
}

export interface RecipientFormView {
  mode: "add" | "change";
  recipientId: string;
  /** The recipient's name in the form's heading when it is changed. */
  name: string;
  values: RecipientFormValues;
  roles: Option[];
  languages: LanguageOption[];
  businesses: Option[];
  /** How many address rows to render: what is there plus one empty row, at least two. */
  addressRows: number;
}

export interface RecipientsPageView {
  businesses: BusinessChoice[];
  /** True when the tenant has more businesses than the choice lists. */
  moreBusinesses: boolean;
  selected: BusinessChoice | null;
  rows: RecipientRow[];
  summary: RecipientSummary;
  /** True when the business has more recipients than one page shows. */
  moreRecipients: boolean;
  /** Null while the tenant has no business to follow. */
  form: RecipientFormView | null;
  /** True when the page was asked to change a recipient the tenant does not have. */
  editMissing: boolean;
}

export interface RecipientsPageInput {
  tenantKind: TenantKind;
  businesses: readonly BusinessSummary[];
  moreBusinesses: boolean;
  selected: BusinessChoice | null;
  recipients: readonly Recipient[];
  moreRecipients: boolean;
  templates: readonly Template[];
  /** The recipient being changed, or null to add one. */
  editing: Recipient | null;
  editMissing: boolean;
  /** The id the add form submits with, minted for this render. */
  newRecipientId: string;
  /** The page itself, without a query. */
  pageHref: string;
}

/** The name a recipient goes by: its organisation, or its role when it names none. */
export function recipientName(recipient: Pick<Recipient, "orgLabel" | "role">): string {
  return recipient.orgLabel === "" ? t(ROLE_LABEL[recipient.role]) : recipient.orgLabel;
}

/** The businesses a recipient follows, by name: the service orders them by id, which reads as
 * random, so they are sorted for the page. */
function businessNames(recipient: Recipient, names: ReadonlyMap<string, string>): string[] {
  return recipient.businesses
    .map((link) => names.get(link.businessId) ?? (link.label === "" ? link.businessId : link.label))
    .sort((a, b) => a.localeCompare(b));
}

function deliveryLabel(recipient: Recipient): string {
  if (recipient.byDigest && recipient.digestMode === "off") return t("recipients.delivery.firm");
  return t(DIGEST_LABEL[recipient.digestMode]);
}

export function recipientRows(
  recipients: readonly Recipient[],
  businesses: readonly BusinessChoice[],
  hrefFor: (recipientId: string) => string,
): RecipientRow[] {
  const names = new Map(businesses.map((business) => [business.id, business.name]));
  return sortRecipients(recipients).map((recipient) => ({
    id: recipient.id,
    orgLabel: recipient.orgLabel,
    roleLabel: t(ROLE_LABEL[recipient.role]),
    addresses: recipient.addresses.map((address) => ({
      channel: address.channel,
      channelLabel: t(CHANNEL_LABEL[address.channel]),
      address: address.address,
    })),
    businesses: businessNames(recipient, names),
    languageLabel: languageName(recipient.language),
    deliveryLabel: deliveryLabel(recipient),
    updatedAt: recipient.updatedAt,
    editHref: hrefFor(recipient.id),
  }));
}

function formView(input: RecipientsPageInput, selected: BusinessChoice): RecipientFormView {
  const { editing } = input;
  const roles = [...rolesFor(input.tenantKind)];
  if (editing !== null && !roles.includes(editing.role)) roles.push(editing.role);
  const languages = languageOptions([
    DEFAULT_LANGUAGE,
    ...input.templates.map((template) => template.language),
    ...(editing === null ? [] : [editing.language]),
  ]);
  const businesses: Option[] = input.businesses.map((business) => ({
    value: business.id,
    label: business.name,
  }));
  for (const link of editing?.businesses ?? []) {
    if (!businesses.some((option) => option.value === link.businessId)) {
      businesses.push({
        value: link.businessId,
        label: link.label === "" ? link.businessId : link.label,
      });
    }
  }
  const values: RecipientFormValues =
    editing === null
      ? {
          role: roles[0] ?? "owner",
          language: DEFAULT_LANGUAGE,
          digestMode: "off",
          orgLabel: "",
          addresses: [],
          businessIds: [selected.id],
        }
      : {
          role: editing.role,
          language: editing.language,
          digestMode: editing.digestMode,
          orgLabel: editing.orgLabel,
          addresses: editing.addresses,
          businessIds: editing.businesses.map((link) => link.businessId),
        };
  return {
    mode: editing === null ? "add" : "change",
    recipientId: editing === null ? input.newRecipientId : editing.id,
    name: editing === null ? "" : recipientName(editing),
    values,
    roles: roles.map((role) => ({ value: role, label: t(ROLE_LABEL[role]) })),
    languages,
    businesses,
    addressRows: Math.min(MAX_ADDRESSES, Math.max(2, values.addresses.length + 1)),
  };
}

export function recipientsPageView(input: RecipientsPageInput): RecipientsPageView {
  const businesses = input.businesses.map(({ id, name }) => ({ id, name }));
  const { selected } = input;
  const editHref = (recipientId: string) =>
    withQuery(input.pageHref, { business: selected?.id, edit: recipientId });
  return {
    businesses,
    moreBusinesses: input.moreBusinesses,
    selected,
    rows: selected === null ? [] : recipientRows(input.recipients, businesses, editHref),
    summary: recipientSummary(input.recipients),
    moreRecipients: input.moreRecipients,
    form: selected === null ? null : formView(input, selected),
    editMissing: input.editMissing,
  };
}
