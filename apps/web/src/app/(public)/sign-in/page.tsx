import type { Metadata } from "next";
import { redirect } from "next/navigation";
import {
  DevSignInForm,
  SignInUnavailable,
  seedState,
  signIn,
  signInFormOptions,
} from "@/features/auth";
import { providerFor } from "@/server/auth/provider";
import { verifySession } from "@/server/dal";
import { getEnv } from "@/server/env";
import { homeFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { safeNext } from "@/shared/lib/url";

const SCREEN = screenById("system.sign-in");

export const metadata: Metadata = { title: SCREEN.title };

// The session cookie and the provider configuration are read per request.
export const dynamic = "force-dynamic";

interface SearchParams {
  next?: string | string[];
}

/** A signed-in visitor is sent on; everyone else gets the configured provider's form. */
export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { next } = await searchParams;
  const nextPath = safeNext(typeof next === "string" ? next : undefined, "");
  const session = await verifySession();
  if (session !== null) redirect(nextPath === "" ? homeFor(session) : nextPath);
  const provider = providerFor(getEnv());
  if (!provider.ok) {
    return (
      <SignInUnavailable
        title={provider.error.message}
        detail={provider.error.problem?.detail ?? undefined}
      />
    );
  }
  if (!provider.value.methods.includes("fake")) {
    return <SignInUnavailable title={t("signIn.unavailableNoForm")} />;
  }
  const seed = await seedState();
  return (
    <DevSignInForm
      action={signIn}
      options={signInFormOptions()}
      next={nextPath === "" ? undefined : nextPath}
      seededTenantId={seed?.tenantId ?? null}
    />
  );
}
