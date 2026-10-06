import type { Route } from "next";
import Link from "next/link";

export interface KeysetPagerProps {
  /** The next page, continuing after the last row shown; null on the last page. */
  nextHref: string | null;
  /** The first page, from a later one; null on the first page. */
  firstHref: string | null;
  /** Names the navigation, as each list pages its own way. */
  label: string;
  nextLabel: string;
  firstLabel: string;
}

/**
 * The way through a list a service pages by key: the next page, and back to the first from a
 * later one. A keyset has no previous page to offer, so there is none. Both links are GET
 * addresses, so a page of the list can be shared.
 */
export function KeysetPager({
  nextHref,
  firstHref,
  label,
  nextLabel,
  firstLabel,
}: KeysetPagerProps) {
  if (nextHref === null && firstHref === null) return null;
  return (
    <nav aria-label={label} data-slot="keyset-pager">
      <ul className="flex flex-wrap gap-4 text-sm">
        {firstHref === null ? null : (
          <li>
            <Link
              href={firstHref as Route}
              className="text-primary underline-offset-2 hover:underline"
            >
              {firstLabel}
            </Link>
          </li>
        )}
        {nextHref === null ? null : (
          <li>
            <Link
              href={nextHref as Route}
              className="text-primary underline-offset-2 hover:underline"
            >
              {nextLabel}
            </Link>
          </li>
        )}
      </ul>
    </nav>
  );
}
