"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@compliancewatch/ui";
import type { NavLink } from "@/shared/config/nav";
import { activeHref } from "@/shared/lib/url";

export interface SectionNavProps {
  items: readonly NavLink[];
  /** Names the navigation landmark ("Pages of this business"). */
  label: string;
  className?: string;
}

/**
 * The pages of one section (the pages of a business) as a row of links, the current one marked
 * with aria-current and an underline; the query string does not change which one is current.
 * Renders nothing with fewer than two links.
 */
export function SectionNav({ items, label, className }: SectionNavProps) {
  const current = activeHref(
    items.map((item) => item.href),
    usePathname(),
  );
  if (items.length < 2) return null;
  return (
    <nav aria-label={label} data-slot="section-nav" className={className}>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 border-b border-line text-sm">
        {items.map((item) => {
          const active = item.href === current;
          return (
            <li key={item.id}>
              <Link
                href={item.href as Route}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "-mb-px inline-block border-b-2 px-1 py-2 hover:text-fg",
                  active
                    ? "border-primary font-medium text-fg"
                    : "border-transparent text-fg-muted",
                )}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
