import type { Route } from "next";
import Link from "next/link";
import { Banner, EmptyState, KeyValue, PageHeader } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import type { GroupRead, GroupView } from "../model/group";
import { DecisionPanel, type DecideAction } from "./decision-panel";
import type { AccessView } from "./decision-shared";
import { ItemsTable } from "./items-table";

export interface EntityGroupViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The queue, for the way back when no group is named. */
  queueHref: string;
  read: GroupRead;
  /** The group with its open mentions; null when none was named or the read failed. */
  view: GroupView | null;
  access: AccessView | null;
  error?: ServiceErrorLike;
  /** The decision action, bound to the group; offered only when access allows it. */
  decide: DecideAction | null;
}

function BackToQueue({ href }: { href: string }) {
  return (
    <Link href={href as Route} className="text-sm text-primary underline-offset-2 hover:underline">
      {t("entityReview.backToQueue")}
    </Link>
  );
}

/**
 * One review group: its type and proposed name, the open mentions with a link to where each was
 * found, a way to ask the canonical entities tool how the name resolves, and the decision. The
 * decision is offered when the session may send it (the role, web.admin_rulebook_writes and the
 * review token); otherwise the page says which of them holds it back and lists the mentions.
 */
export function EntityGroupView({
  title,
  crumbs,
  queueHref,
  read,
  view,
  access,
  error,
  decide,
}: EntityGroupViewProps) {
  const header = (
    <PageHeader
      title={title}
      description={t("entityReview.group.intro")}
      breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
    />
  );
  if (read.kind !== "ok") {
    return (
      <div data-slot="entity-group" className="flex max-w-5xl flex-col gap-6">
        {header}
        {read.kind === "invalid" ? (
          <Banner tone="warning" title={t("entityReview.group.invalidTitle")}>
            {read.message}
          </Banner>
        ) : null}
        <EmptyState
          title={t("entityReview.group.noneTitle")}
          body={t("entityReview.group.noneBody")}
          action={<BackToQueue href={queueHref} />}
        />
      </div>
    );
  }
  return (
    <div data-slot="entity-group" className="flex max-w-5xl flex-col gap-6">
      {header}
      {view === null ? null : (
        <div className="flex flex-col gap-3">
          <KeyValue
            data-slot="group-facts"
            items={[
              { key: "type", label: t("entityReview.group.type"), value: view.typeLabel },
              {
                key: "name",
                label: t("entityReview.group.name"),
                value: <span className="font-mono text-sm">{view.nameLabel}</span>,
              },
              {
                key: "open",
                label: t("entityReview.group.open"),
                value: String(view.items.length),
              },
            ]}
          />
          <ul className="flex flex-wrap gap-4 text-sm">
            {view.resolveHref === null ? null : (
              <li>
                <Link
                  href={view.resolveHref as Route}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  {t("entityReview.resolveName")}
                </Link>
              </li>
            )}
            <li>
              <BackToQueue href={view.queueHref} />
            </li>
          </ul>
        </div>
      )}
      {error !== undefined ? <ServiceError error={error} /> : null}
      {view === null ? null : access?.allowed === true && decide !== null ? (
        <DecisionPanel
          action={decide}
          items={view.items}
          typeLabel={view.typeLabel}
          nameLabel={view.nameLabel}
          resolveHref={view.resolveHref}
          queueHref={view.queueHref}
          nameable={view.nameable}
        />
      ) : (
        <>
          {access === null || access.allowed ? null : (
            <Banner tone="warning" title={access.title} data-slot="decision-refused">
              {access.detail ?? null}
            </Banner>
          )}
          {view.items.length === 0 ? (
            <EmptyState
              title={t("entityReview.group.emptyTitle")}
              body={t("entityReview.group.emptyBody")}
              action={<BackToQueue href={view.queueHref} />}
            />
          ) : (
            <ItemsTable items={view.items} nameLabel={view.nameLabel} />
          )}
        </>
      )}
    </div>
  );
}
