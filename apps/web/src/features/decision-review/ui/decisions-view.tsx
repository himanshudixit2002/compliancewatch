import type { Route } from "next";
import Link from "next/link";
import { Button, EmptyState, Field, Input, PageHeader, Select } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t, type MessageKey } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import {
  LOOKUP_FIELDS,
  STATUS_FILTERS,
  statusFilterLabel,
  type DecisionLookup,
  type StatusFilter,
} from "../model/lookup";
import type { DecisionsView as DecisionsViewModel } from "../queries";
import { ReviewItemCard } from "./review-item-card";
import type { ResolveAction } from "./resolve-panel";

export interface DecisionsViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The screen itself, without a query: the lookup form's action. */
  pageHref: string;
  lookup: DecisionLookup;
  /** The items the lookup found; null before a lookup, or when the read failed. */
  view: DecisionsViewModel | null;
  error?: ServiceErrorLike;
  /** The resolve action; the view binds it to the tenant and each item. */
  resolve: (
    tenantId: string,
    itemId: string,
    ...rest: Parameters<ResolveAction>
  ) => ReturnType<ResolveAction>;
}

const EMPTY: Readonly<Record<StatusFilter, { title: MessageKey; body: MessageKey }>> = {
  open: { title: "decisions.empty.openTitle", body: "decisions.empty.openBody" },
  resolved: { title: "decisions.empty.resolvedTitle", body: "decisions.empty.resolvedBody" },
  all: { title: "decisions.empty.allTitle", body: "decisions.empty.allBody" },
};

function lookupValues(lookup: DecisionLookup): { tenant: string; status: StatusFilter } {
  if (lookup.kind === "ok") return { tenant: lookup.tenantId, status: lookup.status };
  if (lookup.kind === "invalid") return { tenant: lookup.value, status: lookup.status };
  return { tenant: "", status: lookup.status };
}

/**
 * The decision review queue of one tenant: the decisions the engine could not settle by itself
 * (a condition in words nobody judged, a judgement below the threshold). The review routes act
 * for the tenant named in x-tenant-id, so the screen is a lookup by tenant id, a GET form with the
 * status to list. Every regulatory role reads; a reviewer or an admin settles an open item.
 */
export function DecisionsView({
  title,
  crumbs,
  pageHref,
  lookup,
  view,
  error,
  resolve,
}: DecisionsViewProps) {
  const values = lookupValues(lookup);
  return (
    <div data-slot="decisions" className="flex max-w-5xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("decisions.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <form
        method="get"
        action={pageHref}
        aria-label={t("decisions.lookupLabel")}
        data-slot="decisions-lookup"
        noValidate
        className="grid max-w-3xl items-end gap-3 sm:grid-cols-[2fr_1fr_auto]"
      >
        <Field
          id="decisions-tenant"
          label={t("decisions.tenant")}
          error={lookup.kind === "invalid" ? lookup.error : undefined}
          required
        >
          <Input
            name={LOOKUP_FIELDS.tenant}
            defaultValue={values.tenant}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Field id="decisions-status" label={t("decisions.statusField")}>
          <Select
            name={LOOKUP_FIELDS.status}
            defaultValue={values.status}
            options={STATUS_FILTERS.map((status) => ({
              value: status,
              label: statusFilterLabel(status),
            }))}
          />
        </Field>
        <Button type="submit" variant="secondary">
          {t("decisions.lookup")}
        </Button>
      </form>
      {lookup.kind !== "ok" ? (
        <p className="max-w-prose text-sm text-fg-muted">{t("decisions.lookupHelp")}</p>
      ) : (
        <section aria-labelledby="decisions-items" className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h2 id="decisions-items" className="text-lg font-semibold text-fg">
              {t("decisions.itemsTitle")}
            </h2>
            <p className="text-sm text-fg-muted" data-slot="lookup-facts">
              {t("decisions.itemsFacts", {
                tenant: lookup.tenantId,
                status: statusFilterLabel(lookup.status),
              })}
            </p>
          </div>
          {error !== undefined ? <ServiceError error={error} /> : null}
          {view === null ? null : view.items.length === 0 ? (
            <EmptyState title={t(EMPTY[view.status].title)} body={t(EMPTY[view.status].body)} />
          ) : (
            <div className="flex flex-col gap-4" data-slot="review-items">
              {view.items.map((item) => (
                <ReviewItemCard
                  key={item.id}
                  item={item}
                  resolveAction={
                    view.canResolve && item.status === "open"
                      ? resolve.bind(null, view.tenantId, item.id)
                      : null
                  }
                />
              ))}
            </div>
          )}
          {view === null || (view.nextHref === null && view.firstHref === null) ? null : (
            <nav aria-label={t("decisions.pager")}>
              <ul className="flex flex-wrap gap-4 text-sm">
                {view.firstHref === null ? null : (
                  <li>
                    <Link
                      href={view.firstHref as Route}
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      {t("decisions.first")}
                    </Link>
                  </li>
                )}
                {view.nextHref === null ? null : (
                  <li>
                    <Link
                      href={view.nextHref as Route}
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      {t("decisions.next")}
                    </Link>
                  </li>
                )}
              </ul>
            </nav>
          )}
        </section>
      )}
    </div>
  );
}
