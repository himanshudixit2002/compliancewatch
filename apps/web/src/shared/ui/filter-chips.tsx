import type { Route } from "next";
import Link from "next/link";
import { cn } from "@compliancewatch/ui";

export interface FilterChip {
  key: string;
  label: string;
  href: string;
  current: boolean;
}

export interface FilterChipsProps {
  /** Names the navigation: what the chips choose ("Show candidates by status"). */
  label: string;
  chips: readonly FilterChip[];
  className?: string;
}

/**
 * A row of links that each show the list one way (one status, every status). They are links,
 * not buttons, so a filtered list has its own address; the current one carries
 * `aria-current="true"` and the filled style, so the choice reads without colour too.
 */
export function FilterChips({ label, chips, className }: FilterChipsProps) {
  return (
    <nav aria-label={label} data-slot="filter-chips" className={className}>
      <ul className="flex flex-wrap gap-2">
        {chips.map((chip) => (
          <li key={chip.key}>
            <Link
              href={chip.href as Route}
              aria-current={chip.current ? "true" : undefined}
              data-chip={chip.key}
              className={cn(
                "inline-flex items-center rounded-full border px-3 py-1 text-sm font-medium underline-offset-2 hover:underline",
                chip.current
                  ? "border-primary bg-primary text-primary-fg"
                  : "border-line-strong bg-surface text-fg",
              )}
            >
              {chip.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
