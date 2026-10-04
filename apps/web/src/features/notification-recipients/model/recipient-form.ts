import type {
  Channel,
  DigestMode,
  RecipientAddress,
  RecipientRole,
} from "@/entities/notification/types";
import { t } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { isE164, isEmailAddress, isUuid, normalisePhone } from "@/shared/lib/identifiers";
import { DIGEST_MODES } from "./recipients";

/**
 * The recipient form: who the recipient is (role and organisation), the addresses in the order
 * they are tried, the language, whether reminders wait for the daily digest, and the businesses
 * the recipient hears about. The address fields are named as the service names a field in a
 * 422 (`addresses.0.address`), so its field errors land on the right input. The checks here are
 * shapes only; the service owns the rules.
 */
export const MAX_ADDRESSES = 10;
export const LABEL_MAX_LENGTH = 200;

export const RECIPIENT_FIELDS = {
  recipientId: "recipient_id",
  /** The business the page was showing, to return to. */
  returnBusiness: "return_business",
  role: "role",
  language: "language",
  digestMode: "digest_mode",
  orgLabel: "org_label",
  businesses: "businesses",
} as const;

export type RecipientFields = typeof RECIPIENT_FIELDS;

export function addressField(index: number): string {
  return `addresses.${index}.address`;
}

export function channelField(index: number): string {
  return `addresses.${index}.channel`;
}

export const ADDRESS_CHANNELS: readonly Channel[] = ["whatsapp", "email"];

/** What the form offered, which is what it accepts back. */
export interface RecipientFormOffer {
  roles: readonly RecipientRole[];
  languages: readonly string[];
  businessIds: readonly string[];
}

export interface ParsedRecipientForm {
  recipientId: string;
  returnBusiness: string | null;
  role: RecipientRole;
  language: string;
  digestMode: DigestMode;
  orgLabel: string;
  addresses: RecipientAddress[];
  businessIds: string[];
}

export type RecipientFormResult =
  | { ok: true; value: ParsedRecipientForm }
  | { ok: false; fieldErrors?: FieldErrors; formErrors?: string[] };

function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function isChannel(value: string): value is Channel {
  return (ADDRESS_CHANNELS as readonly string[]).includes(value);
}

function isDigestMode(value: string): value is DigestMode {
  return (DIGEST_MODES as readonly string[]).includes(value);
}

/** A typed address in the form the service stores: +digits, or lower case. */
export function normaliseAddress(
  channel: Channel,
  raw: string,
): { ok: true; address: string } | { ok: false; error: string } {
  if (channel === "whatsapp") {
    const number = normalisePhone(raw);
    return isE164(number)
      ? { ok: true, address: number }
      : { ok: false, error: t("recipients.error.whatsapp") };
  }
  const address = raw.toLowerCase();
  return isEmailAddress(address)
    ? { ok: true, address }
    : { ok: false, error: t("recipients.error.email") };
}

/** The addresses in their rows' order, empty rows left out, each checked and once. */
function parseAddresses(formData: FormData, errors: Record<string, string[]>): RecipientAddress[] {
  const addresses: RecipientAddress[] = [];
  const seen = new Set<string>();
  for (let index = 0; index < MAX_ADDRESSES; index += 1) {
    const raw = text(formData, addressField(index));
    if (raw === "") continue;
    const channel = text(formData, channelField(index));
    if (!isChannel(channel)) {
      errors[channelField(index)] = [t("recipients.error.channel")];
      continue;
    }
    const normalised = normaliseAddress(channel, raw);
    if (!normalised.ok) {
      errors[addressField(index)] = [normalised.error];
      continue;
    }
    const key = `${channel} ${normalised.address}`;
    if (seen.has(key)) {
      errors[addressField(index)] = [t("recipients.error.duplicate")];
      continue;
    }
    seen.add(key);
    addresses.push({ channel, address: normalised.address });
  }
  return addresses;
}

export function parseRecipientForm(
  formData: FormData,
  offer: RecipientFormOffer,
): RecipientFormResult {
  const recipientId = text(formData, RECIPIENT_FIELDS.recipientId).toLowerCase();
  if (!isUuid(recipientId)) return { ok: false, formErrors: [t("recipients.error.stale")] };
  const returnBusiness = text(formData, RECIPIENT_FIELDS.returnBusiness).toLowerCase();

  const errors: Record<string, string[]> = {};
  const role = text(formData, RECIPIENT_FIELDS.role);
  if (!(offer.roles as readonly string[]).includes(role)) {
    errors[RECIPIENT_FIELDS.role] = [t("recipients.error.role")];
  }
  const language = text(formData, RECIPIENT_FIELDS.language);
  if (!offer.languages.includes(language)) {
    errors[RECIPIENT_FIELDS.language] = [t("recipients.error.language")];
  }
  const digestMode = text(formData, RECIPIENT_FIELDS.digestMode);
  if (!isDigestMode(digestMode)) {
    errors[RECIPIENT_FIELDS.digestMode] = [t("recipients.error.digest")];
  }
  const orgLabel = text(formData, RECIPIENT_FIELDS.orgLabel);
  if (orgLabel.length > LABEL_MAX_LENGTH) {
    errors[RECIPIENT_FIELDS.orgLabel] = [t("recipients.error.orgLabel", { max: LABEL_MAX_LENGTH })];
  }
  const addresses = parseAddresses(formData, errors);
  const addressErrors = Object.keys(errors).some((key) => key.startsWith("addresses."));
  if (addresses.length === 0 && !addressErrors) {
    errors[addressField(0)] = [t("recipients.error.noAddress")];
  }
  const businessIds = [
    ...new Set(
      formData
        .getAll(RECIPIENT_FIELDS.businesses)
        .map((value) => (typeof value === "string" ? value.trim().toLowerCase() : "")),
    ),
  ].filter((value) => value !== "");
  if (businessIds.length === 0) {
    errors[RECIPIENT_FIELDS.businesses] = [t("recipients.error.businesses")];
  } else if (businessIds.some((id) => !offer.businessIds.includes(id))) {
    errors[RECIPIENT_FIELDS.businesses] = [t("recipients.error.unknownBusiness")];
  }

  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  return {
    ok: true,
    value: {
      recipientId,
      returnBusiness: isUuid(returnBusiness) ? returnBusiness : null,
      role: role as RecipientRole,
      language,
      digestMode: digestMode as DigestMode,
      orgLabel,
      addresses,
      businessIds,
    },
  };
}
