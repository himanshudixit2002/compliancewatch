"use client";

import type { CSSProperties } from "react";
import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { Toaster as Sonner, toast, type ToasterProps } from "sonner";

export { toast };
export type { ToasterProps };

/* Sonner reads these variables for its normal and rich-colour toasts, so the toasts follow the
   tokens (and the .dark class) without a theme prop. */
const tokenStyle = {
  "--normal-bg": "var(--surface-raised)",
  "--normal-text": "var(--fg)",
  "--normal-border": "var(--line)",
  "--success-bg": "var(--success)",
  "--success-text": "var(--success-fg)",
  "--success-border": "var(--success)",
  "--error-bg": "var(--danger)",
  "--error-text": "var(--danger-fg)",
  "--error-border": "var(--danger)",
  "--warning-bg": "var(--warning)",
  "--warning-text": "var(--warning-fg)",
  "--warning-border": "var(--warning)",
  "--info-bg": "var(--info)",
  "--info-text": "var(--info-fg)",
  "--info-border": "var(--info)",
  "--border-radius": "var(--radius-md)",
} as CSSProperties;

/**
 * Mount once in the root layout. `toast(...)` from this module queues a message; sonner renders
 * the list in an aria-live="polite" region.
 */
export function Toaster({ style, ...props }: ToasterProps) {
  return (
    <Sonner
      richColors
      closeButton
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4" aria-hidden="true" />,
        info: <InfoIcon className="size-4" aria-hidden="true" />,
        warning: <TriangleAlertIcon className="size-4" aria-hidden="true" />,
        error: <OctagonXIcon className="size-4" aria-hidden="true" />,
        loading: <Loader2Icon className="size-4 animate-spin" aria-hidden="true" />,
      }}
      style={{ ...tokenStyle, ...style }}
      {...props}
    />
  );
}
