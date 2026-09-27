import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "success" | "warning" | "danger";

export interface BadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
}

const toneClasses: Record<BadgeTone, string> = {
  neutral: "bg-gray-100 text-gray-800",
  success: "bg-green-100 text-green-800",
  warning: "bg-amber-100 text-amber-800",
  danger: "bg-red-100 text-red-800",
};

/** Small status label; first component of the shared kit (guide section 12: Tailwind, shadcn/ui style). */
export function Badge({ tone = "neutral", children }: BadgeProps) {
  return (
    <span
      data-tone={tone}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${toneClasses[tone]}`}
    >
      {children}
    </span>
  );
}
