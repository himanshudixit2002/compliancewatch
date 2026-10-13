import type { Metadata } from "next";
import type { Route } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Banner, Button, PageHeader } from "@compliancewatch/ui";
import { SIGN_UP_FIELDS, SIGN_UP_KINDS, SignUpForm, pendingSignIn, signUp } from "@/features/auth";
import type { SignUpKindOption } from "@/features/auth";
import { verifySession } from "@/server/dal";
import { homeFor } from "@/shared/config/nav";
import { firstRoleFor, requiresMfa } from "@/shared/config/roles";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";

const SCREEN = screenById("system.sign-up");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

const KIND_KEYS = {
  business: { label: "tenantKind.business", description: "signUp.kind.business" },
  ca_firm: { label: "tenantKind.ca_firm", description: "signUp.kind.ca_firm" },
} as const;

/**
 * Create the account of a person identity does not know yet: the pending sign-in (cw_pending)
 * is the proof of who they are; the form asks what kind of account and its name. Without a
 * pending sign-in there is nothing to sign up: the page says to sign in first.
 */
export default async function SignUpPage() {
  const session = await verifySession();
  if (session !== null) redirect(homeFor(session));
  const pending = await pendingSignIn();
  const signInHref = hrefFor(screenById("system.sign-in"));
  if (pending === null) {
    return (
      <div data-slot="sign-up-start" className="flex max-w-xl flex-col gap-6">
        <PageHeader title={t("signUp.title")} description={t("signUp.startIntro")} />
        <Banner
          tone="info"
          action={
            <Button asChild size="sm">
              <Link href={signInHref as Route}>{t("common.signIn")}</Link>
            </Button>
          }
        >
          {t("signUp.startBody")}
        </Banner>
      </div>
    );
  }
  const kinds: SignUpKindOption[] = SIGN_UP_KINDS.map((kind) => ({
    value: kind,
    label: t(KIND_KEYS[kind].label),
    description: t(KIND_KEYS[kind].description),
    needsMfa: requiresMfa([firstRoleFor(kind)]),
  }));
  const contact = pending.contact.phone ?? pending.contact.email ?? "";
  return <SignUpForm action={signUp} fields={SIGN_UP_FIELDS} kinds={kinds} contact={contact} />;
}
