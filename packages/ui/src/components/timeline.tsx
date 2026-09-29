import type { ComponentProps, ReactNode } from "react";
import { cn } from "../lib/cn";
import type { Tone } from "../tokens";

const dotClasses: Record<Tone, string> = {
  neutral: "bg-line-strong",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
};

export interface TimelineEvent {
  id: string;
  /** The formatted time as the app wants it shown (IST helpers live in the app). */
  label: string;
  /** Machine-readable time for the <time> element. */
  dateTime?: string;
  title: ReactNode;
  body?: ReactNode;
  tone?: Tone;
}

export interface TimelineProps extends ComponentProps<"ol"> {
  events: readonly TimelineEvent[];
}

/** Dated events in order, one dot per event. */
export function Timeline({ events, className, ...props }: TimelineProps) {
  return (
    <ol
      data-slot="timeline"
      className={cn("flex flex-col gap-4 border-l border-line pl-4", className)}
      {...props}
    >
      {events.map((event) => {
        const tone = event.tone ?? "neutral";
        return (
          <li key={event.id} data-tone={tone} className="relative">
            <span
              aria-hidden="true"
              className={cn(
                "absolute top-1.5 -left-[21px] size-2.5 rounded-full ring-2 ring-bg",
                dotClasses[tone],
              )}
            />
            <time dateTime={event.dateTime} className="block text-xs text-fg-muted">
              {event.label}
            </time>
            <p className="text-sm font-medium text-fg">{event.title}</p>
            {event.body ? <div className="text-sm text-fg-muted">{event.body}</div> : null}
          </li>
        );
      })}
    </ol>
  );
}
