"use client";

import type { Route } from "next";
import NextLink from "next/link";
import type { NavLinkProps } from "@compliancewatch/ui";

/**
 * next/link with the UI kit's link props, so the shells keep client-side navigation. The hrefs
 * come from the registry through hrefFor(), which already checks them against the route tree.
 */
export function RouterLink({ href, children, ...rest }: NavLinkProps) {
  return (
    <NextLink href={href as Route} {...rest}>
      {children}
    </NextLink>
  );
}
