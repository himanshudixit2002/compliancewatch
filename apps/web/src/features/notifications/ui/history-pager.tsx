import type { Route } from "next";
import Link from "next/link";
import { t } from "@/shared/i18n";

export interface HistoryPagerProps {
  nextHref: string | null;
  firstHref: string | null;
}

/**
 * The way through a long history: the next page, and back to the newest from a later one. The
 * service pages with an opaque cursor, so there is no "previous page" to offer.
 */
export function HistoryPager({ nextHref, firstHref }: HistoryPagerProps) {
  if (nextHref === null && firstHref === null) return null;
  return (
    <nav aria-label={t("notificationLog.pager")} data-slot="history-pager">
      <ul className="flex flex-wrap gap-4 text-sm">
        {firstHref === null ? null : (
          <li>
            <Link
              href={firstHref as Route}
              className="text-primary underline-offset-2 hover:underline"
            >
              {t("notificationLog.first")}
            </Link>
          </li>
        )}
        {nextHref === null ? null : (
          <li>
            <Link
              href={nextHref as Route}
              className="text-primary underline-offset-2 hover:underline"
            >
              {t("notificationLog.next")}
            </Link>
          </li>
        )}
      </ul>
    </nav>
  );
}
