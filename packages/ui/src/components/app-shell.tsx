"use client";

import { useId } from "react";
import type { ComponentProps, ElementType, ReactNode } from "react";
import { MenuIcon } from "lucide-react";
import { cn } from "../lib/cn";
import { Button } from "./button";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "./sheet";

export interface NavItem {
  href: string;
  label: string;
  active?: boolean;
  /**
   * A short note shown after the link, for example "Waiting" for a tool that is not built yet.
   * It stays outside the link's name and is announced as the link's description.
   */
  hint?: string;
}

export interface NavLinkProps {
  href: string;
  className?: string;
  children: ReactNode;
  "aria-current"?: "page";
  "aria-describedby"?: string;
}

export interface AppShellProps extends ComponentProps<"div"> {
  productName?: string;
  homeHref?: string;
  items: readonly NavItem[];
  /** Account controls rendered at the end of the header. */
  userMenu?: ReactNode;
  /** The app passes next/link here so navigation stays client-side; defaults to <a>. */
  Link?: ElementType<NavLinkProps>;
  /** Names the small-screen navigation panel. */
  navLabel?: string;
}

export function SkipLink({
  href = "#main",
  children = "Skip to main content",
}: {
  href?: string;
  children?: ReactNode;
}) {
  return (
    <a
      href={href}
      data-slot="skip-link"
      className="sr-only rounded-md bg-primary px-3 py-2 text-primary-fg focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50"
    >
      {children}
    </a>
  );
}

export function NavLinks({
  items,
  Link = "a",
  className,
}: {
  items: readonly NavItem[];
  Link?: ElementType<NavLinkProps>;
  className?: string;
}) {
  const baseId = useId();
  return (
    <ul className={cn("flex gap-1", className)}>
      {items.map((item, index) => {
        const hintId = item.hint === undefined ? undefined : `${baseId}-hint-${index}`;
        return (
          <li
            key={item.href}
            className={item.hint === undefined ? undefined : "flex flex-wrap items-center gap-x-1"}
          >
            <Link
              href={item.href}
              aria-current={item.active ? "page" : undefined}
              aria-describedby={hintId}
              className={cn(
                "block rounded-md px-3 py-2 text-sm font-medium text-fg-muted hover:bg-fg/5 hover:text-fg",
                item.active && "bg-surface text-fg",
              )}
            >
              {item.label}
            </Link>
            {item.hint === undefined ? null : (
              <span id={hintId} data-slot="nav-hint" className="text-xs text-fg-muted">
                {item.hint}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Header with the product name, the primary navigation (a Sheet under the md breakpoint), a
 * user-menu slot, and <main id="main"> that the skip link targets.
 */
export function AppShell({
  productName = "ComplianceWatch",
  homeHref = "/",
  items,
  userMenu,
  Link = "a",
  navLabel = "Navigation",
  className,
  children,
  ...props
}: AppShellProps) {
  return (
    <div
      data-slot="app-shell"
      className={cn("flex min-h-screen flex-col bg-bg text-fg", className)}
      {...props}
    >
      <SkipLink />
      <header className="border-b bg-surface-raised">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4">
          <Sheet>
            <SheetTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="md:hidden"
                aria-label={`Open ${navLabel.toLowerCase()}`}
              >
                <MenuIcon aria-hidden="true" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="p-0">
              <SheetTitle className="px-4 pt-4">{navLabel}</SheetTitle>
              <SheetDescription className="sr-only">Links to the main sections</SheetDescription>
              <nav aria-label={navLabel} className="p-2">
                <NavLinks items={items} Link={Link} className="flex-col" />
              </nav>
            </SheetContent>
          </Sheet>
          <Link href={homeHref} className="text-base font-semibold text-fg">
            {productName}
          </Link>
          <nav aria-label="Primary" className="hidden md:block">
            <NavLinks items={items} Link={Link} />
          </nav>
          <div className="ml-auto flex items-center gap-2">{userMenu}</div>
        </div>
      </header>
      <main
        id="main"
        tabIndex={-1}
        className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 outline-none"
      >
        {children}
      </main>
    </div>
  );
}
