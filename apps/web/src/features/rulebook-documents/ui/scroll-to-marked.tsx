"use client";

import { useEffect } from "react";

export interface ScrollToMarkedProps {
  /** The id of the clause a link asked to mark. */
  anchorId: string;
}

/**
 * Brings the marked clause into view when the page opens from a link that marks one (a mention,
 * a quote) and carries no #fragment of its own, and puts focus there so the next Tab continues
 * from the clause. A #fragment in the address wins: the browser has already scrolled to it.
 */
export function ScrollToMarked({ anchorId }: ScrollToMarkedProps) {
  useEffect(() => {
    if (window.location.hash !== "") return;
    const target = document.getElementById(anchorId);
    if (target === null) return;
    target.scrollIntoView({ block: "center" });
    target.focus({ preventScroll: true });
  }, [anchorId]);
  return null;
}
