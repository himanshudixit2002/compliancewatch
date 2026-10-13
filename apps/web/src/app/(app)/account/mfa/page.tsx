import type { Metadata } from "next";
import { roleLabel } from "@/entities/screen/mappers";
import {
  MFA_FIELDS,
  MfaView,
  OTP_LENGTH,
  enrolAuthenticator,
  pendingSignIn,
  removeAuthenticator,
  verifySecondFactor,
} from "@/features/auth";
import type { MfaFactorView } from "@/features/auth";
import { providerFor } from "@/server/auth/provider";
import { verifySession } from "@/server/dal";
import { getEnv } from "@/server/env";
import { MFA_REQUIRED_ROLES, requiresMfa } from "@/shared/config/roles";
import { hrefFor, screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";
import { safeNext } from "@/shared/lib/url";

const SCREEN = screenById("account.mfa");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface SearchParams {
  next?: string | string[];
}

/**
 * Two-step verification, for a signed-in person (who enrols, verifies or removes a factor)
 * or for a pending sign-in whose roles need the factor before identity issues a session (the
 * proxy lets that pending cookie through here). Nobody at all is told to sign in first.
 */
export default async function MfaPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const { next } = await searchParams;
  const nextPath = safeNext(typeof next === "string" ? next : undefined, "");
  const session = await verifySession();
  const pending = session === null ? await pendingSignIn() : null;
  const provider = providerFor(getEnv());
  if (!provider.ok) return <ServiceError heading={SCREEN.title} error={provider.error} />;
  const who = session !== null ? "session" : pending !== null ? "pending" : "anonymous";
  const roles = session?.roles ?? [];
  let factors: MfaFactorView[] = [];
  if (session !== null && provider.value.mfaMode === "totp" && session.providerRefreshToken) {
    const refreshed = await provider.value.refresh(session.providerRefreshToken);
    if (refreshed.ok) {
      const listed = await provider.value.mfa.listFactors(refreshed.value);
      if (listed.ok) {
        factors = listed.value.map((factor) => ({
          id: factor.id,
          status: factor.status,
          friendlyName: factor.friendlyName,
        }));
      }
    }
  }
  return (
    <MfaView
      mode={provider.value.mfaMode}
      who={who}
      required={who === "pending" || requiresMfa(roles)}
      verified={session?.mfa ?? false}
      requiringRoles={MFA_REQUIRED_ROLES.map(roleLabel)}
      factors={factors}
      verify={verifySecondFactor}
      enrol={enrolAuthenticator}
      remove={removeAuthenticator}
      fields={MFA_FIELDS}
      next={nextPath === "" ? undefined : nextPath}
      signInHref={hrefFor(screenById("system.sign-in"))}
      accountHref={hrefFor(screenById("account.home"))}
      codeLength={OTP_LENGTH}
    />
  );
}
