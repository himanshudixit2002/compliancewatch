import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  FanOutView,
  controlFanOut,
  getFanOutPage,
  rollBackVersion,
  setFanOutHold,
  versionName,
} from "@/features/fan-outs";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { isHexUuid } from "@/shared/lib/identifiers";
import { withQuery } from "@/shared/lib/url";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.fan-out");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ ruleVersionId: string }>;
}

export default async function FanOutPage({ params }: Props) {
  const { ruleVersionId } = await params;
  const session = await requireScreenSession(SCREEN, { ruleVersionId });
  if (!isHexUuid(ruleVersionId)) notFound();
  const id = ruleVersionId.toLowerCase();
  const page = await getFanOutPage(session, id);
  if (!page.ok) {
    if (page.error.kind === "not_found" || page.error.kind === "validation") notFound();
    return <ServiceError heading={SCREEN.title} error={page.error} />;
  }
  const { run, version } = page.value;
  const name = run === null && version === null ? id : versionName(run ?? { ruleKey: id }, version);
  const crumbs = breadcrumbsFor("admin.fan-out", { ruleVersionId: id }).map((crumb) =>
    crumb.id === SCREEN.id ? { ...crumb, label: name } : crumb,
  );
  return (
    <FanOutView
      title={t("fanOut.title", { name })}
      name={name}
      crumbs={crumbs}
      view={page.value}
      hrefs={{
        fanOut: (other) => hrefFor(SCREEN, { ruleVersionId: other }),
        version: hrefFor(screenById("admin.rulebook.version"), { ruleVersionId: id }),
        dryRun: page.value.canControl
          ? withQuery(hrefFor(screenById("admin.impact")), { rule_version_id: id })
          : null,
      }}
      holdAction={setFanOutHold.bind(null, id)}
      controlAction={controlFanOut.bind(null, id)}
      rollbackAction={rollBackVersion.bind(null, id)}
    />
  );
}
