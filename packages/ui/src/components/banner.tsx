import type { ComponentProps, ReactNode } from "react";
import {
  CircleAlertIcon,
  CircleCheckIcon,
  InfoIcon,
  MessageSquareIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { cn } from "../lib/cn";
import type { Tone } from "../tokens";

const toneClasses: Record<Tone, string> = {
  neutral: "border-line-strong bg-surface",
  success: "border-success bg-success/10",
  warning: "border-warning bg-warning/10",
  danger: "border-danger bg-danger/10",
  info: "border-info bg-info/10",
};

const iconClasses: Record<Tone, string> = {
  neutral: "text-fg-muted",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  info: "text-info",
};

const icons: Record<Tone, typeof InfoIcon> = {
  neutral: MessageSquareIcon,
  success: CircleCheckIcon,
  warning: TriangleAlertIcon,
  danger: CircleAlertIcon,
  info: InfoIcon,
};

export interface BannerProps extends Omit<ComponentProps<"div">, "title"> {
  tone?: Tone;
  title?: ReactNode;
  /** Buttons or links rendered after the message. */
  action?: ReactNode;
}

/** An inline message. Danger banners are alerts; every other tone is a polite status. */
export function Banner({
  tone = "neutral",
  title,
  action,
  className,
  children,
  ...props
}: BannerProps) {
  const Icon = icons[tone];
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      data-slot="banner"
      data-tone={tone}
      className={cn(
        "flex gap-3 rounded-md border-l-4 border-y border-r border-y-line border-r-line p-3 text-sm text-fg",
        toneClasses[tone],
        className,
      )}
      {...props}
    >
      <Icon aria-hidden="true" className={cn("mt-0.5 size-4 shrink-0", iconClasses[tone])} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {title ? <p className="font-medium">{title}</p> : null}
        {children ? (
          <div className="text-fg-muted [&_a]:text-primary [&_a]:underline">{children}</div>
        ) : null}
        {action ? <div className="mt-1 flex flex-wrap gap-2">{action}</div> : null}
      </div>
    </div>
  );
}
