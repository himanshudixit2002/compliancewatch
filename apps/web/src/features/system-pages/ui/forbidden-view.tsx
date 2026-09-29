import type { Route } from "next";
import Link from "next/link";
import { Button, PageHeader } from "@compliancewatch/ui";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";

/** The redirect target of a failed role gate: what is missing, and where to go instead. */
export function ForbiddenView() {
  const home = hrefFor(screenById("system.home"));
  const signIn = hrefFor(screenById("system.sign-in"));
  return (
    <div data-slot="forbidden" className="flex max-w-2xl flex-col gap-6">
      <PageHeader title={t("forbidden.title")} description={t("forbidden.body")} />
      <div className="flex flex-wrap gap-2">
        <Button asChild>
          <Link href={home}>{t("forbidden.home")}</Link>
        </Button>
        <Button asChild variant="secondary">
          <Link href={signIn as Route}>{t("forbidden.signIn")}</Link>
        </Button>
      </div>
    </div>
  );
}
