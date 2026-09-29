import { StatusChip } from "@compliancewatch/ui";
import type { Tone } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export type ScreenStatus = "live" | "waiting" | "planned";

const TONES: Readonly<Record<ScreenStatus, Tone>> = {
  live: "success",
  waiting: "warning",
  planned: "neutral",
};

export interface ScreenStatusChipProps {
  status: ScreenStatus;
  className?: string;
}

/** A registry status as a chip whose text, not its colour, says what the status is. */
export function ScreenStatusChip({ status, className }: ScreenStatusChipProps) {
  return (
    <StatusChip
      status={status}
      tone={TONES[status]}
      label={t(`status.${status}`)}
      className={className}
    />
  );
}
