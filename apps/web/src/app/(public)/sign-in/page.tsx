import type { Metadata } from "next";
import { redirect } from "next/navigation";
import {
  DevSignInForm,
  MethodLinks,
  OTP_LENGTH,
  RESEND_AFTER_SECONDS,
  SIGN_IN_FIELDS,
  SignInForm,
  SignInUnavailable,
  readSignInMethod,
  seedState,
  sendEmailLink,
  signIn,
  signInFormOptions,
  signInNoticeKey,
  startPhoneSignIn,
  verifyPhoneCode,
} from "@/features/auth";
import type { MethodLink, SignInMethodName } from "@/features/auth";
import { providerFor } from "@/server/auth/provider";
import { verifySession } from "@/server/dal";
import { getEnv } from "@/server/env";
import { homeFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { safeNext, withQuery } from "@/shared/lib/url";

const SCREEN = screenById("system.sign-in");

export const metadata: Metadata = { title: SCREEN.title };

// The session cookie and the provider configuration are read per request.
export const dynamic = "force-dynamic";

interface SearchParams {
  next?: string | string[];
  method?: string | string[];
  reason?: string | string[];
  error?: string | string[];
}

const METHOD_LABELS: Record<SignInMethodName, string> = {
  dev: "signIn.method.dev",
  phone: "signIn.method.phone",
  email: "signIn.method.email",
};

/**
 * A signed-in visitor is sent on; everyone else gets the configured provider's forms: by
 * phone (a code) or by email (a link), and in local and test with the fake adapter the
 * development sign-in (a persona) as well, which is the first on offer there.
 */
export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const query = await searchParams;
  const nextPath = safeNext(typeof query.next === "string" ? query.next : undefined, "");
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
  const available = provider.value.methods;
  const method = readSignInMethod(query.method, available);
  const noticeKey = signInNoticeKey(query);
  const notice = noticeKey === undefined ? undefined : t(noticeKey);
  const links: MethodLink[] = available
    .filter((name) => name !== method)
    .map((name) => ({
      method: name,
      href: withQuery(hrefFor(SCREEN), { method: name, next: nextPath }),
      label: t(METHOD_LABELS[name] as "signIn.method.dev"),
    }));
  if (method === "dev") {
    const seed = await seedState();
    return (
      <div className="flex flex-col gap-6">
        <DevSignInForm
          action={signIn}
          options={signInFormOptions()}
          next={nextPath === "" ? undefined : nextPath}
          seededTenantId={seed?.tenantId ?? null}
          notice={notice}
        />
        <MethodLinks links={links} />
      </div>
    );
  }
  return (
    <SignInForm
      method={method}
      startPhone={startPhoneSignIn}
      verifyCode={verifyPhoneCode}
      sendEmail={sendEmailLink}
      fields={SIGN_IN_FIELDS}
      next={nextPath === "" ? undefined : nextPath}
      notice={notice}
      otherMethods={links}
      devNotice={provider.value.name === "fake"}
      resendAfterSeconds={RESEND_AFTER_SECONDS}
      codeLength={OTP_LENGTH}
    />
  );
}
