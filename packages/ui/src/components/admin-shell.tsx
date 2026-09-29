"use client";

import type { ComponentProps, ElementType, ReactNode } from "react";
import { MenuIcon } from "lucide-react";
import { cn } from "../lib/cn";
import { NavLinks, SkipLink, type NavItem, type NavLinkProps } from "./app-shell";
import { Button } from "./button";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "./sheet";

export interface NavGroup {
  label: string;
  items: readonly NavItem[];
}

export interface AdminShellProps extends ComponentProps<"div"> {
  productName?: string;
  homeHref?: string;
  groups: readonly NavGroup[];
  /** Shown in the internal banner, for example "local" or "staging". */
  environment: string;
  userMenu?: ReactNode;
  Link?: ElementType<NavLinkProps>;
}

function ToolNav({
  groups,
  Link,
}: {
  groups: readonly NavGroup[];
  Link: ElementType<NavLinkProps>;
}) {
  return (
    <nav aria-label="Internal tools" className="flex flex-col gap-4">
      {groups.map((group) => (
        <div key={group.label}>
          <p className="px-3 pb-1 text-xs font-semibold tracking-wide text-fg-muted uppercase">
            {group.label}
          </p>
          <NavLinks items={group.items} Link={Link} className="flex-col" />
        </div>
      ))}
    </nav>
  );
}

/** The /admin skeleton: an internal banner with the environment, grouped tools in a sidebar. */
export function AdminShell({
  productName = "ComplianceWatch",
  homeHref = "/admin",
  groups,
  environment,
  userMenu,
  Link = "a",
  className,
  children,
  ...props
}: AdminShellProps) {
  return (
    <div
      data-slot="admin-shell"
      className={cn("flex min-h-screen flex-col bg-bg text-fg", className)}
      {...props}
    >
      <SkipLink />
      <div
        role="status"
        data-slot="internal-banner"
        className="bg-fg px-4 py-1 text-center text-xs font-medium text-bg"
      >
        Internal tools. Environment: <span data-slot="environment">{environment}</span>
      </div>
      <header className="border-b bg-surface-raised">
        <div className="flex h-14 items-center gap-4 px-4">
          <Sheet>
            <SheetTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="md:hidden"
                aria-label="Open internal tools"
              >
                <MenuIcon aria-hidden="true" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="overflow-y-auto p-4">
              <SheetTitle>Internal tools</SheetTitle>
              <SheetDescription className="sr-only">
                Grouped links to the admin tools
              </SheetDescription>
              <ToolNav groups={groups} Link={Link} />
            </SheetContent>
          </Sheet>
          <Link href={homeHref} className="text-base font-semibold text-fg">
            {productName} <span className="text-fg-muted">admin</span>
          </Link>
          <div className="ml-auto flex items-center gap-2">{userMenu}</div>
        </div>
      </header>
      <div className="flex flex-1">
        <aside className="hidden w-64 shrink-0 border-r bg-surface p-4 md:block">
          <ToolNav groups={groups} Link={Link} />
        </aside>
        <main id="main" tabIndex={-1} className="min-w-0 flex-1 px-6 py-6 outline-none">
          {children}
        </main>
      </div>
    </div>
  );
}
