import type { Route } from "next";
import Link from "next/link";
import { t } from "@/shared/i18n";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import { StatCard } from "@/shared/ui/stat-card";
import type { StatsStrip as StatsStripModel } from "../model/stats";

export interface StatsStripProps {
  strip: StatsStripModel | null;
  /** The stats could not be read: the queue still shows, with this error in the strip's place. */
  error?: ServiceErrorLike;
}

/**
 * The queue in numbers above it: how many tasks are open, claimed and decided, the acceptance
 * rate of the rule candidates and how long the oldest open task has waited, with the stats page.
 */
export function StatsStrip({ strip, error }: StatsStripProps) {
  return (
    <section
      aria-labelledby="review-strip-heading"
      data-slot="review-strip"
      className="flex flex-col gap-3"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="review-strip-heading" className="text-lg font-semibold text-fg">
          {t("reviewStats.stripHeading")}
        </h2>
        {strip === null ? null : (
          <Link
            href={strip.statsHref as Route}
            className="text-sm text-primary underline-offset-2 hover:underline"
          >
            {t("reviewStats.stripLink")}
          </Link>
        )}
      </div>
      {error !== undefined ? <ServiceError error={error} /> : null}
      {strip === null ? null : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5" data-slot="review-strip-cards">
          <StatCard label={t("reviewStats.open")} value={strip.open} tone="warning" />
          <StatCard label={t("reviewStats.claimed")} value={strip.claimed} tone="info" />
          <StatCard label={t("reviewStats.decided")} value={strip.decided} tone="success" />
          <StatCard
            label={t("reviewStats.acceptance")}
            value={strip.acceptance}
            hint={t("reviewStats.acceptanceHint")}
          />
          <StatCard label={t("reviewStats.oldest")} value={strip.oldest} />
        </div>
      )}
    </section>
  );
}
