import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { VersionView, getVersionPage, saveCitations, takeStep } from "@/features/rule-versions";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { isHexUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.rulebook.version");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ ruleVersionId: string }>;
}

export default async function RuleVersionPage({ params }: Props) {
  const { ruleVersionId } = await params;
  const session = await requireScreenSession(SCREEN, { ruleVersionId });
  if (!isHexUuid(ruleVersionId)) notFound();
  const id = ruleVersionId.toLowerCase();
  const page = await getVersionPage(id, { session });
  if (!page.ok) {
    if (page.error.kind === "not_found" || page.error.kind === "validation") notFound();
    return <ServiceError heading={SCREEN.title} error={page.error} />;
  }
  const { version } = page.value;
  const crumbs = breadcrumbsFor("admin.rulebook.version", { ruleVersionId: id }).map((crumb) =>
    crumb.id === SCREEN.id
      ? {
          ...crumb,
          label: t("ruleVersions.versionName", { rule: version.ruleKey, version: version.version }),
        }
      : crumb,
  );
  return (
    <VersionView
      view={page.value}
      crumbs={crumbs}
      citeAction={saveCitations.bind(null, id)}
      stepAction={takeStep.bind(null, id)}
      sessionUserId={session.userId}
      sessionName={session.displayName}
    />
  );
}
