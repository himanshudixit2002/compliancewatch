import { Banner, KeyValue, PageHeader } from "@compliancewatch/ui";
import type { KeyValueItem } from "@compliancewatch/ui";
import { roleLabel } from "@/entities/screen/mappers";
import { expiresAtDate } from "@/entities/session/mappers";
import type { SessionDto } from "@/entities/session/types";
import { t } from "@/shared/i18n";
import type { MessageKey } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { SignOutButton } from "@/shared/ui/sign-out-button";

export interface AccountViewProps {
  session: SessionDto;
}

const KIND_KEYS: Record<SessionDto["tenantKind"], MessageKey> = {
  business: "tenantKind.business",
  ca_firm: "tenantKind.ca_firm",
  internal: "tenantKind.internal",
};

const PROVIDER_KEYS: Record<SessionDto["provider"], MessageKey> = {
  fake: "account.provider.fake",
  supabase: "account.provider.supabase",
};

function mfaText(session: SessionDto): string {
  if (!session.mfa) return t("account.mfaNone");
  return session.provider === "fake" ? t("account.mfaAsserted") : t("account.mfaVerified");
}

/** The facts the session carries, with a way out; profile fields arrive with identity's /me. */
export function AccountView({ session }: AccountViewProps) {
  const items: KeyValueItem[] = [
    { key: "name", label: t("account.displayName"), value: session.displayName },
    {
      key: "user",
      label: t("account.userId"),
      value: <code className="font-mono text-xs">{session.userId}</code>,
      copy: session.userId,
    },
    {
      key: "tenant",
      label: t("account.tenantId"),
      value: <code className="font-mono text-xs">{session.tenantId}</code>,
      copy: session.tenantId,
    },
    { key: "kind", label: t("account.tenantKind"), value: t(KIND_KEYS[session.tenantKind]) },
    { key: "roles", label: t("account.roles"), value: session.roles.map(roleLabel).join(", ") },
    { key: "mfa", label: t("account.mfa"), value: mfaText(session) },
    {
      key: "issued",
      label: t("account.issuedAt"),
      value: formatDateTime(new Date(session.issuedAt * 1000)),
    },
    {
      key: "expires",
      label: t("account.expiresAt"),
      value: formatDateTime(expiresAtDate(session)),
    },
    { key: "provider", label: t("account.provider"), value: t(PROVIDER_KEYS[session.provider]) },
  ];
  return (
    <div data-slot="account" className="flex max-w-2xl flex-col gap-6">
      <PageHeader
        title={t("account.title")}
        description={t("account.intro")}
        actions={<SignOutButton />}
      />
      <KeyValue items={items} aria-label={t("account.facts")} />
      <Banner tone="info">{t("account.profileNote")}</Banner>
    </div>
  );
}
