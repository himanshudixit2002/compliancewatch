import { StatusChip } from "@compliancewatch/ui";
import type { Tone } from "@compliancewatch/ui";
import type { ValueState } from "@/entities/business/types";
import { stateLabel } from "../model/values";

const TONES: Readonly<Record<ValueState, Tone>> = {
  known: "success",
  unsure: "warning",
  not_applicable: "neutral",
};

export interface ValueStateChipProps {
  state: ValueState;
  className?: string;
}

/** How sure an answer is, as a chip whose text says it: Known, Not sure, Does not apply. */
export function ValueStateChip({ state, className }: ValueStateChipProps) {
  return (
    <StatusChip
      status={state}
      tone={TONES[state]}
      label={stateLabel(state)}
      className={className}
    />
  );
}
