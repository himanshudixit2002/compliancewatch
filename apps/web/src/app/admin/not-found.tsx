import Link from "next/link";
import { Button, EmptyState } from "@compliancewatch/ui";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";

// notFound() in an admin tool (an unknown path, a record that does not exist) renders here,
// inside the admin shell. A session without a regulatory role never reaches it: the admin
// layout's own notFound() is answered by the root not-found page, with no admin markup.
export default function AdminNotFound() {
  return (
    <EmptyState
      data-slot="not-found"
      heading="h1"
      title={t("notFound.title")}
      body={t("notFound.body")}
      action={
        <Button asChild>
          <Link href={hrefFor(screenById("admin.home"))}>{t("admin.notFound.back")}</Link>
        </Button>
      }
    />
  );
}
