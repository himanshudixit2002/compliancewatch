import { Badge } from "@compliancewatch/ui";
import type { Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * The applicability engine's words, shared by the screens that show its decisions: a result as a
 * badge whose words carry the meaning ("Applies", "Does not apply", "Not sure", a result the
 * engine never guesses, with "needs review" when a person has to look), and the level of the
 * business hierarchy a rule is decided at. The obligation rows, the decision review queue, the
 * fan-outs, the impact explorer and a CA firm's affected clients show them the same way. The
 * values are the engine's (`Applicability`, `AttributeLevel`); the types are spelled out here
 * because shared code reads no entity.
 */
export type ApplicabilityResult = "applies" | "not_applicable" | "unsure";

export type HierarchyLevel = "entity" | "registration" | "location";

const LEVELS: Readonly<Record<HierarchyLevel, MessageKey>> = {
  entity: "applicability.level.entity",
  registration: "applicability.level.registration",
  location: "applicability.level.location",
};

/** "Registrations (GSTIN)": the businesses of a level, as a rule is decided for them. */
export function levelLabel(level: HierarchyLevel): string {
  return t(LEVELS[level]);
}

const LABELS: Readonly<Record<ApplicabilityResult, MessageKey>> = {
  applies: "applicability.applies",
  not_applicable: "applicability.notApplicable",
  unsure: "applicability.unsure",
};

const TONES: Readonly<Record<ApplicabilityResult, Tone>> = {
  applies: "success",
  not_applicable: "neutral",
  unsure: "warning",
};

export function applicabilityLabel(result: ApplicabilityResult, needsReview = false): string {
  const label = t(LABELS[result]);
  return needsReview ? t("applicability.withReview", { result: label }) : label;
}

export function applicabilityTone(result: ApplicabilityResult): Tone {
  return TONES[result];
}

export interface ApplicabilityBadgeProps {
  result: ApplicabilityResult;
  needsReview?: boolean;
  className?: string;
}

export function ApplicabilityBadge({
  result,
  needsReview = false,
  className,
}: ApplicabilityBadgeProps) {
  return (
    <Badge
      tone={TONES[result]}
      data-slot="applicability-badge"
      data-result={result}
      className={className}
    >
      {applicabilityLabel(result, needsReview)}
    </Badge>
  );
}
