import type { Route } from "next";
import Link from "next/link";
import { Banner, Button, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export interface EmailSentViewProps {
  /** The sign-in page, to try another method. */
  signInHref: string;
  /** Local and test only: the link the fake adapter would have sent, to open here. */
  devLink?: string;
}

/** After the email step: what to do next, and the link itself where nothing is sent. */
export function EmailSentView({ signInHref, devLink }: EmailSentViewProps) {
  return (
    <div data-slot="email-sent" className="flex max-w-md flex-col gap-6">
      <PageHeader title={t("signIn.emailSentTitle")} description={t("signIn.emailSentBody")} />
      {devLink !== undefined ? (
        <Banner
          tone="info"
          title={t("signIn.devLinkTitle")}
          action={
            <Button asChild size="sm">
              <a href={devLink} data-slot="dev-email-link">
                {t("signIn.devLinkOpen")}
              </a>
            </Button>
          }
        >
          {t("signIn.devLinkBody")}
        </Banner>
      ) : null}
      <p className="text-sm text-fg-muted">
        <Link href={signInHref as Route} className="underline hover:text-fg">
          {t("signIn.emailSentBack")}
        </Link>
      </p>
    </div>
  );
}
