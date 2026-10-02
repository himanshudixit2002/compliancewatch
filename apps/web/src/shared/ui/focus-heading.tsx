"use client";

import { useEffect } from "react";

export interface FocusHeadingProps {
  /** Moves focus only when true, such as after an answer brought the next question. */
  active: boolean;
  /** The heading to focus; the page's h1 inside main by default. */
  selector?: string;
}

/**
 * Moves focus to the page's heading once, on mount, so a screen reader starts at the new
 * question after a form moved the page on. The heading becomes focusable by script only
 * (tabindex -1) and keeps its place in the reading order. Renders nothing.
 */
export function FocusHeading({ active, selector = "main h1" }: FocusHeadingProps) {
  useEffect(() => {
    if (!active) return;
    const heading = document.querySelector<HTMLElement>(selector);
    if (heading === null) return;
    if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
    heading.focus();
  }, [active, selector]);
  return null;
}
