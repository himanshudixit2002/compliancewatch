import type { Route } from "next";
import Link from "next/link";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";

export interface BreadcrumbsProps {
  /** Root first, the current page last; one crumb renders nothing. */
  crumbs: readonly Crumb[];
}

/** The parent chain of a screen; the last crumb is the current page and is not a link. */
export function Breadcrumbs({ crumbs }: BreadcrumbsProps) {
  if (crumbs.length < 2) return null;
  const last = crumbs.length - 1;
  return (
    <nav aria-label={t("nav.breadcrumbs")} data-slot="breadcrumbs">
      <ol className="flex flex-wrap items-center gap-1 text-sm text-fg-muted">
        {crumbs.map((crumb, index) => (
          <li key={crumb.id} className="flex items-center gap-1">
            {index === last ? (
              <span aria-current="page" className="text-fg">
                {crumb.label}
              </span>
            ) : (
              <>
                <Link href={crumb.href as Route} className="hover:text-fg hover:underline">
                  {crumb.label}
                </Link>
                <span aria-hidden="true">/</span>
              </>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
