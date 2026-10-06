import type { Route } from "next";
import Link from "next/link";
import { t } from "@/shared/i18n";

export interface ListPagerProps {
  nextHref: string | null;
  firstHref: string | null;
  label: string;
}

/**
 * The way through a long list: the next page, and back to the first from a later one. The pages
 * follow a key, not a number, so there is no "previous page" to offer.
 */
export function ListPager({ nextHref, firstHref, label }: ListPagerProps) {
  if (nextHref === null && firstHref === null) return null;
  return (
    <nav aria-label={label} data-slot="list-pager">
      <ul className="flex flex-wrap gap-4 text-sm">
        {firstHref === null ? null : (
          <li>
            <Link
              href={firstHref as Route}
              className="text-primary underline-offset-2 hover:underline"
            >
              {t("obligations.pager.first")}
            </Link>
          </li>
        )}
        {nextHref === null ? null : (
          <li>
            <Link
              href={nextHref as Route}
              className="text-primary underline-offset-2 hover:underline"
            >
              {t("obligations.pager.next")}
            </Link>
          </li>
        )}
      </ul>
    </nav>
  );
}
