import Link from "next/link";
import { Button, EmptyState } from "@compliancewatch/ui";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";

/** The 404 page: nothing at this address, and a way home. */
export function NotFoundView() {
  return (
    <EmptyState
      data-slot="not-found"
      heading="h1"
      title={t("notFound.title")}
      body={t("notFound.body")}
      action={
        <Button asChild>
          <Link href={hrefFor(screenById("system.home"))}>{t("notFound.home")}</Link>
        </Button>
      }
    />
  );
}
