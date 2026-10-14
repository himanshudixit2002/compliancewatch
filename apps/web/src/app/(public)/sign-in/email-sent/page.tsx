import type { Metadata } from "next";
import { EmailSentView, callbackUrl, pendingSignIn } from "@/features/auth";
import { getEnv, isLocalOrTest } from "@/server/env";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("system.sign-in-email-sent");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

/**
 * After the email step. With the fake adapter in local and test nothing was sent: the pending
 * cookie holds the token the link carries, and the page shows the link to open.
 */
export default async function EmailSentPage() {
  const env = getEnv();
  const pending = await pendingSignIn();
  let devLink: string | undefined;
  if (pending !== null && pending.provider === "fake" && isLocalOrTest(env.CW_WEB_ENV)) {
    const link = new URL(await callbackUrl(pending.next, env));
    link.searchParams.set("token_hash", pending.session.accessToken);
    link.searchParams.set("type", "email");
    devLink = link.toString();
  }
  return (
    <EmailSentView
      signInHref={hrefFor(screenById("system.sign-in"))}
      {...(devLink === undefined ? {} : { devLink })}
    />
  );
}
